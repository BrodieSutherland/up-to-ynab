# Up payload capture summary

Captured: 2026-10-20T16:15:05
Transactions scanned: 2000; webhook log entries: 1026

## Accounts (type/ownership: count)

- SAVER/INDIVIDUAL: 3
- TRANSACTIONAL/INDIVIDUAL: 1

## Transactions by case

| Case | Count | transferAccount set | HELD | settledAt null |
|---|---|---|---|---|
| purchase_foreign_currency | 1 | 0 | 0 | 0 |
| purchase_plain | 182 | 0 | 0 | 0 |
| purchase_with_message | 118 | 0 | 0 | 0 |
| purchase_with_round_up | 836 | 0 | 1 | 1 |
| round_up_saver_side | 847 | 847 | 0 | 0 |
| transfer_mirror | 3 | 3 | 0 | 0 |
| transfer_originating | 13 | 13 | 0 | 0 |

## Matched Transfer pairs (originating + mirror)

| Kind | Pairs | Both sides transferAccount set |
|---|---|---|
| transfer | 3 | 3 |

## Webhook log

- TRANSACTION_CREATED: 740
- TRANSACTION_DELETED: 10
- TRANSACTION_SETTLED: 276

Delivery status:

- BAD_RESPONSE_CODE: 624
- DELIVERED: 400
- UNDELIVERABLE: 2

## Cases with no example found

- cover_originating
- cover_mirror
- forward_originating
- forward_mirror
- quick_save_originating
- quick_save_mirror
