# Changelog

Each release lists what changed and anything to do when upgrading. Major releases also have an upgrade section in the [README](README.md).

## 3.1.0

### Upgrading

1. **Back up the database file first.** On first start the schema is migrated automatically and the unused `payee_category_mappings` and `processed_transactions` tables are dropped. Downgrading to 3.0 afterwards is not supported.
2. **The webhook is replaced once.** `/webhook` now needs Up's signature, and Up only gives a webhook its secret when it is created. Your existing webhook has no stored secret, so on first start it is deleted and a new one is created (look for "Webhook created" in the logs). This needs `WEBHOOK_URL`; without it nothing is registered and `/webhook` rejects every event.
3. **Set `ADMIN_TOKEN`** to protect `/refresh`, `/backfill` and `/ledger`. If it is unset they stay open and a warning is logged at startup.
4. To catch up on anything missed, run `/refresh`, then `POST /backfill?since=YYYY-MM-DD`.

### Added

- Settled transactions are marked cleared in YNAB, and the amount is corrected if it changed. Reconciled transactions are left alone. (#111)
- Cancelled holds are deleted from YNAB, or flagged red if you already cleared them.
- `/webhook` verifies the `X-Up-Authenticity-Signature` header and answers 401 without a valid one.
- `ADMIN_TOKEN` protects the admin endpoints with a Bearer token.
- `POST /backfill?since=YYYY-MM-DD` forwards missed Up transactions, including ones skipped because their account wasn't in YNAB yet. Stops after 150 YNAB creates per run.
- `GET /ledger/{up_transaction_id}` shows what the app recorded for one transaction.
- Startup warnings when the configured budget is archived, or when no Up account matches a YNAB account.
- A Postman collection for debugging in `docs/postman/`.

### Changed

- Database migrations run at startup.
- Payees renamed by YNAB rename rules keep their Category match.

## 3.0.0

Accounts are matched by name, transfers are recognised, and every handled transaction is recorded. See [Upgrading to 3.0](README.md#upgrading-to-30).
