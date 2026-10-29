# UP to YNAB Transaction Sync

Automatically sync transactions from [Up Bank](https://up.com.au/) to [YNAB](https://www.ynab.com/) using webhooks and APIs.

[![CI](https://github.com/BrodieSutherland/up-to-ynab/actions/workflows/ci.yml/badge.svg)](https://github.com/BrodieSutherland/up-to-ynab/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/docker/v/brodiesutherland/up-to-ynab?label=docker)](https://hub.docker.com/r/brodiesutherland/up-to-ynab)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)

## Features

- **Real-time sync** via Up Bank webhooks
- **Category match** from your YNAB history (all-time, rebuilt every 6 hours and on `/refresh`)
- **Per-account routing** by name
- **Failed forwards retried** (the webhook answers 503, so Up redelivers)
- **Webhook registered and kept tidy** automatically
- **Transfers** booked once, as YNAB transfers
- **Health monitoring** with built-in endpoints
- **Docker ready** with production and development configurations
- **Comprehensive testing** with a 97% branch-coverage gate in CI
- **Security focused** with non-root containers and vulnerability scanning

## Quick Start

### Prerequisites

- Up Bank API token ([get one here](https://developer.up.com.au/))
- YNAB Personal Access Token ([get one here](https://app.ynab.com/settings/developer))
- YNAB Budget ID: the UUID in the YNAB web app's URL when the budget is open (`app.ynab.com/<budget-id>/budget`). Use the budget you actually work in, not an archived one; the app accepts any budget your token can read.
- YNAB accounts named exactly like your Up accounts
- Public webhook URL (for receiving Up Bank notifications)

### Docker Deployment (Recommended)

1. **Clone and setup:**
   ```bash
   git clone https://github.com/BrodieSutherland/up-to-ynab.git
   cd up-to-ynab
   cp .env.example .env
   ```

2. **Configure environment variables in `.env`:**
   ```bash
   UP_API_TOKEN=your_up_api_token_here
   YNAB_API_TOKEN=your_ynab_token_here
   YNAB_BUDGET_ID=your_budget_id_here
   WEBHOOK_URL=https://your-domain.com/webhook
   ```

   **Important:** All API tokens are required for the application to function properly. The application will show configuration errors if tokens are missing or invalid.

3. **Start production environment:**
   ```bash
   ./scripts/start-prod.sh
   ```

The application will be available at `http://localhost:5001`.

### Prebuilt Image

Images are published to Docker Hub as `brodiesutherland/up-to-ynab` (`3.0.0`, `3.0`, `3` and `latest`). Pin a version so an upgrade only happens when you choose:

```yaml
services:
  up-to-ynab:
    image: brodiesutherland/up-to-ynab:3.0.0
    restart: unless-stopped
    ports:
      - "5001:5001"
    environment:
      UP_API_TOKEN: ${UP_API_TOKEN}
      YNAB_API_TOKEN: ${YNAB_API_TOKEN}
      YNAB_BUDGET_ID: ${YNAB_BUDGET_ID}
      WEBHOOK_URL: https://your-domain.com/webhook
      DATABASE_URL: sqlite+aiosqlite:////app/data/up_to_ynab.db
    volumes:
      - ./data:/app/data
```

The container runs as uid 1000, so the host `data` folder must be writable by that user. Without the volume, the Ledger is lost whenever the container is recreated.

### Development Setup

1. **Start development environment:**
   ```bash
   ./scripts/start-dev.sh
   ```

2. **Run tests:**
   ```bash
   ./scripts/run-tests.sh
   ```

## Upgrading to 3.0

1. **Before upgrading**, rename each YNAB account to match the Up account's `displayName` exactly (case and emoji). Transactions for an Up account with no matching YNAB account are skipped and never retried.
2. Remove `YNAB_ACCOUNT_ID` and `INTERNAL_TRANSFER_STRINGS` from your environment. They are ignored, with a warning at startup, if left in place.
3. `UP_API_TOKEN`, `YNAB_API_TOKEN` and `YNAB_BUDGET_ID` must be set. Startup fails naming the missing or empty field.
4. If you override the container command, use `uvicorn --factory app:create_app`.
5. On startup and on `/refresh`, stale or duplicate webhooks this app created on the same host are deleted. Webhooks this app created on other hosts are only logged, and webhooks it didn't create are never touched.
6. The old `payee_category_mappings` and `processed_transactions` tables are left in place by 3.0. From 3.1 they are dropped automatically on startup.

### Upgrading to 3.1 (webhook signatures)

`/webhook` now verifies Up's signature (`X-Up-Authenticity-Signature`) and answers 401 without a valid one. Up gives each webhook a secret only when it is created, so the app stores it. On the first start after upgrading, your existing webhook has no stored secret: it is deleted and a new one is created (with `WEBHOOK_URL` set). Without `WEBHOOK_URL`, nothing can be registered and `/webhook` rejects every event. Set `ADMIN_TOKEN` to protect `/refresh` and `/backfill`.

Coming from 1.x: set `WEBHOOK_URL=<your-host>/webhook`. The old `/` webhook is removed on first start.

Transactions already forwarded by 2.x are not re-sent. The YNAB `import_id` is now the Up transaction id.

## Configuration

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `UP_API_TOKEN` | ✅ | - | Up Bank API token |
| `YNAB_API_TOKEN` | ✅ | - | YNAB Personal Access Token |
| `YNAB_BUDGET_ID` | ✅ | - | YNAB Budget ID |
| `WEBHOOK_URL` | ❌ | - | Public URL ending `/webhook`; if unset, webhook registration is skipped |
| `ADMIN_TOKEN` | ❌ | - | If set, `/refresh` and `/backfill` need `Authorization: Bearer <token>`; if unset it is open and a warning is logged at startup |
| `UP_BASE_URL` | ❌ | https://api.up.com.au/api/v1/ | Up Bank API base URL |
| `YNAB_BASE_URL` | ❌ | https://api.youneedabudget.com/v1/ | YNAB API base URL |
| `PORT` | ❌ | 5001 | port the container listens on (Docker/compose); pass --port when running uvicorn yourself |
| `DEBUG_MODE` | ❌ | false | Enable debug logging |
| `DATABASE_URL` | ❌ | sqlite+aiosqlite:///./up_to_ynab.db | Database connection URL |

### Account routing

Each Up account's transactions go to the YNAB account with exactly the same name (case and emoji included). Closed YNAB accounts are ignored, and an Up account whose name matches no YNAB account, or more than one, is skipped. See [Upgrading to 3.0](#upgrading-to-30) if you are moving from an earlier version.

### Transfers

Transfers between your Up accounts are recognised by Up's `transferAccount` relationship, not by description text. When both accounts are in YNAB, the half the money left is forwarded as a YNAB transfer and the receiving half is skipped. A Round Up (the Saver's "Round Up" half) is forwarded the same way. If the other account isn't in YNAB, each half is an ordinary transaction (payee is the description, and the Category match applies).

## API Endpoints

- `GET /health` - Health check (`status`, `service`, `version` 3.0.0)
- `POST /webhook` - Up Bank webhook receiver. Needs a valid `X-Up-Authenticity-Signature` (HMAC-SHA256 of the raw body under the secret of a webhook this app created), else 401. Answers 200 with status `forwarded`, `settled`, `skipped`, `deleted`, `flagged` or `ignored`, and 503 on failure so Up retries. `TRANSACTION_CREATED`, `TRANSACTION_SETTLED` and `TRANSACTION_DELETED` are acted on: a deleted transaction that was forwarded is deleted in YNAB if still uncleared, or flagged red if you have cleared or reconciled it; a settled transaction is marked cleared in YNAB (and its amount corrected) unless you have reconciled it.
- `GET /refresh` - Reconciles webhooks, then rebuilds the Budget Index. With `ADMIN_TOKEN` set: `curl -H "Authorization: Bearer $ADMIN_TOKEN" https://your-domain.com/refresh` (401 otherwise)
- `GET /ledger/{up_transaction_id}` - Shows what happened to one Up transaction: `status` (forwarded, skipped, failed or deleted), `reason`, `reason_code`, `ynab_transaction_id`, `attempts` and `updated_at` (UTC); 404 if nothing is recorded. With `ADMIN_TOKEN` set: `curl -H "Authorization: Bearer $ADMIN_TOKEN" http://localhost:5001/ledger/<up-transaction-id>` answers e.g. `{"up_transaction_id": "abc", "status": "skipped", "reason": "Up account not in YNAB", "reason_code": "account_not_in_ynab", "ynab_transaction_id": null, "attempts": 2, "updated_at": "2026-10-30T01:02:03Z"}`.
- `POST /backfill?since=YYYY-MM-DD` - Forwards Up transactions created on or after that day (Australian time) that YNAB doesn't have yet, e.g. after downtime or after adding a YNAB account that was missing (run `/refresh` first). Handled transactions are left alone; transactions skipped because their Up account wasn't in YNAB are retried (as ordinary transactions, never as a YNAB transfer, since the other leg may already be in YNAB, so those two legs aren't linked). Stops after 150 YNAB creates and answers `more_remaining: true`; run it again. With `ADMIN_TOKEN` set: `curl -X POST -H "Authorization: Bearer $ADMIN_TOKEN" "http://localhost:5001/backfill?since=2026-10-01"` answers e.g. `{"forwarded": 12, "skipped": 3, "failed": 0, "already_handled": 40, "more_remaining": false}`. 502 if Up can't be listed.
- `GET /docs` - Interactive API documentation

## Architecture

```
Up webhook ──▶ /webhook ──▶ Forwarder
                              1. Ledger check (already handled?)
                              2. fetch the transaction from Up
                              3. translate with the Budget Index
                              4. create in YNAB
                              5. record the outcome in the Ledger
```

- **Budget Index**: YNAB accounts and the Category match, built at startup, every 6 hours, on `/refresh`, and lazily for an unknown Up account.
- **Ledger**: one row per Up transaction in the SQLite `ledger_entries` table; forwarded and skipped are final (a forwarded row becomes deleted, also final, when Up deletes the transaction), failed is retried on redelivery.

## Limitations

- `/webhook` verifies Up's signature, but `/refresh` and `/backfill` are open unless `ADMIN_TOKEN` is set; anyone who can reach it can trigger a rebuild or a backfill. Set `ADMIN_TOKEN`, or restrict access with a reverse proxy.
- A deleted transaction whose YNAB copy was cleared or reconciled is flagged red for review, not deleted.
- A deleted event for a transaction that reached YNAB through the already-imported path (no YNAB id recorded) is ignored with a warning; remove it by hand.
- If Up starts describing a merchant differently (for example once it recognises the merchant), the new description has no Category match until you categorise it in YNAB again. Payees renamed by your YNAB rename rules are matched.
- An Up account with no matching YNAB account is skipped, and webhooks don't retry it after you add the account; run `/refresh`, then `POST /backfill?since=...` to forward them.
- `/backfill` stops after 150 YNAB creates per run (YNAB allows 200 requests an hour) and works oldest first, so re-run it while `more_remaining` is true; it can report `more_remaining` when everything left was already handled. Its `since` date starts at midnight Australian Eastern Standard Time.
- The database schema is created on startup; there are no migrations.

## Deployment Options

### Docker Compose (Production)
```bash
docker compose up -d
```

### Docker Compose (Development)
Builds the `dev` target of the Dockerfile, with hot reload and the repo bind-mounted at `/app`.
```bash
docker compose -f docker-compose.dev.yml up -d
```

### Manual Installation
```bash
# Install dependencies
pip install -r requirements.txt

# Run application
python -m uvicorn --factory app:create_app --host 0.0.0.0 --port 5001
```

The app refuses to start when a required token or ID (`UP_API_TOKEN`, `YNAB_API_TOKEN`, `YNAB_BUDGET_ID`) is missing or empty; the error names the field.

For development (tests and linting), install `requirements-dev.txt` instead:
```bash
pip install -r requirements-dev.txt
```

## Monitoring

### Health Checks
- **Endpoint:** `GET /health`
- **Response:** JSON with service status and version

### Logging
- Structured JSON logging in production
- Colored console logging in development
- Configurable log levels via `DEBUG_MODE`

### Setup warnings
At startup and on `/refresh` the app logs a warning when:
- no Up account matches a YNAB account (names must be identical); this is also checked on every Budget Index rebuild.
- the YNAB plan named by `YNAB_BUDGET_ID` has "(Archived" in its name ("YNAB plan looks archived"): set `YNAB_BUDGET_ID` to the active plan. If the plan name can't be read, "Could not read YNAB plan name" is logged and startup continues.

### Debugging with Postman
Import both files from `docs/postman/` (`up-to-ynab.postman_collection.json` and `up-to-ynab.postman_environment.json`), select the "up-to-ynab (local)" environment and fill in the variables:
- `baseUrl` defaults to `http://localhost:5001`.
- `adminToken` is your `ADMIN_TOKEN`; leave it empty when `ADMIN_TOKEN` is unset.
- `webhookSecret` is the `secret_key` stored for your webhook in the `webhook_secrets` table of the app's database.
- `upToken`, `ynabToken` and `budgetId` are your Up token, YNAB token and YNAB plan id; `upTransactionId`, `upWebhookId` and `ynabTransactionId` fill the ids the requests use.

The "Webhook > Signed events" requests are signed for you with `webhookSecret`. The unsigned request should get 401. The "Up API" and "YNAB API" folders call the real APIs and only read, except "Ping webhook", which makes Up send a real PING event to the app. Never export the environment with values filled in.

### Docker Health Checks
Built-in Docker health checks monitor service availability every 30 seconds.

## Development

### Project Structure
```
up-to-ynab/
├── app.py            # Composition root, VERSION, routes, lifespan
├── webhooks.py       # Pure webhook reconciliation planner, signature check
├── forwarding/       # Forwarder, backfill, translation, Budget Index, Ledger
├── clients/          # Up and YNAB client Protocols and HTTP adapters
├── database/         # SQLAlchemy models, connection and migration runner
├── migrations/       # Alembic revisions
├── models/           # Pydantic models for Up and YNAB payloads
├── utils/            # config.py (Settings), logging.py
├── tests/            # Test suite
│   ├── fakes/        # In-memory fakes for the client and Ledger seams
│   └── fixtures/up/  # Redacted real Up payloads
└── scripts/          # Deployment and utility scripts
```

### Testing
```bash
# Run all tests
pytest -q

# Run with the coverage gate
pytest -q --cov --cov-branch

# Run specific test file
pytest tests/test_forwarder.py -v

# Or via the script
./scripts/run-tests.sh
```

### Code Quality
```bash
# Format code
black .

# Sort imports
isort .

# Lint code
flake8 .
```

## Contributing

1. Fork the repository
2. Create a feature branch from `develop` (`git checkout -b feature/amazing-feature develop`)
3. Commit your changes, and run `black . && isort . && flake8 .` and `pytest -q --cov --cov-branch`
4. Push the branch (`git push origin feature/amazing-feature`)
5. Open a pull request into `develop`. `main` only receives release merges from `develop`.

## Security

- Non-root Docker containers
- Automated vulnerability scanning with Trivy
- Secure API token handling
- Input validation with Pydantic
- No secrets in logs or error messages
