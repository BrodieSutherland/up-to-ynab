# Up to YNAB

Forwards each transaction from an Up Bank customer's accounts into the matching account of their YNAB budget, so the budget stays current without manual entry.

## Accounts

**Up account**:
One of the customer's accounts at Up: the Spending account or a Saver.
_Avoid_: bank account, source account

**Spending account**:
The single everyday Up account that cards and payments draw from (Up calls it the transactional account).
_Avoid_: transactional account, main account

**Saver**:
An Up savings account, identified to the customer by its display name (emoji included).
_Avoid_: savings account, pot

**YNAB account**:
An account inside the customer's YNAB budget. Each Up account corresponds to exactly one YNAB account with the same name; the Spending account corresponds to the YNAB account named "Spending".
_Avoid_: budget account, target account

## Transactions

**Transfer**:
Money moving between two of the customer's own Up accounts. Up records it as two transactions, one on each account; YNAB records it as one transfer that it books on both accounts itself.
_Avoid_: internal transaction, internal transfer (when meaning the pair)

**Originating side**:
The half of a Transfer recorded on the account the money left ("Transfer to …", "Cover to …", "Quick save transfer to …", "Forward to …"). This is the half forwarded to YNAB, as a transfer.
_Avoid_: outgoing transaction, "to" side

**Mirror side**:
The half of a Transfer recorded on the account the money arrived in ("Transfer from …", "Cover from …", …). Never forwarded, because YNAB creates it from the Originating side.
_Avoid_: incoming transfer, "from" side, duplicate

**Round Up**:
Spare change Up moves from the Spending account into a Saver after a purchase. Treated as a Transfer whose other account is the Spending account.
_Avoid_: roundup, spare change

**Payee**:
Who a transaction was paid to or received from, as Up describes it.
_Avoid_: merchant, description

**Category match**:
The YNAB category a Payee has always been given in the customer's past YNAB transactions. A Payee with zero or several past categories has no Category match.
_Avoid_: payee mapping, category mapping

## Processing

**Budget Index**:
The app's local picture of the customer's YNAB budget: which YNAB account each Up account corresponds to, the transfer payee for each YNAB account, and the Category match for each Payee. Rebuilt from YNAB on demand.
_Avoid_: cache, databases, shelves

**Transaction Translation**:
Turning one Up transaction into either a YNAB transaction to create or a decision to skip it, with the reason.
_Avoid_: conversion, mapping, filtering

**Ledger**:
The record of every Up transaction the app has handled and what happened to it (forwarded, skipped, or failed). A transaction counts as handled once it has been forwarded or deliberately skipped; a failure does not count.
_Avoid_: processed transactions table, dedupe log
