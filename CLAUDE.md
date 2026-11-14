# Ledger Board

Personal finance viewer. `index.html` reads `data.js`, which `tools/ingest.py` builds from bank CSV exports.

## Privacy: this repo is PUBLIC
Never commit transaction data. `data/` and `data.js` are gitignored and must stay that way.
The ledger is persisted in the user's private artifact: https://claude.ai/artifact/AJqX7F8cKp3p85YdToReHY
(published files: `data.js`, `ledger/transactions.csv`, `ledger/rules.json`, `ledger/config.json`,
`ledger/overrides.json`, `ledger/balances.json`).

## When the user drops new CSV exports
1. Restore state if `data/` is empty: Artifact `read` with `path` for each `ledger/*` file above, copy them into `data/`.
2. Copy uploads into `data/inbox/` keeping the bank's filename (Chase files need `Chase####` in the name for the last 4).
   EveryDollar exports go in `data/everydollar/` named `MM-YYYY-EveryDollar-BudgetItems.csv` / `-Transactions.csv`.
3. `python3 -I tools/ingest.py data/inbox/<files> data/everydollar/<files> --report` (dedupes overlaps; drops rows before `start_date`).
   EveryDollar BudgetItems set that month's plan and the category list (group > item); Transactions set
   per-transaction categories (overrides, incl. splits) by matching account + amount + date within 5 days.
   Report lines "not in bank data" mean EveryDollar has a row the bank exports lack. Group totals should equal EveryDollar's.
4. For each uncategorized row, add or extend a regex in `data/rules.json` (preferred) or set `data/overrides.json` `{txId: catId}`; rerun with `--report` until 0 uncategorized. Sanity-check monthly totals in the report.
5. If the user pasted "Ledger Board changes" JSON from the page: `overrides` -> `data/overrides.json` (cat values only),
   `budgets` -> `config.budgets[month][item]`, `buckets` -> `config.savings.buckets[].start`,
   `retirement` -> `config.savings.retirement[].balance`. Suggest a rule when several rows share a payee.
6. Republish: strip the outer `<!doctype>/<html>/<head>/<body>` tags from `index.html` into the scratchpad, and publish to the artifact URL above with `files` = data.js + `ledger/*` from `data/`.
7. Commit only code changes (`index.html`, `tools/`, docs).

## Local copy
The user may also run this locally (see LOCAL_SETUP.md). `tools/pre-commit` blocks data paths; install it in any clone.
To hand the user a fresh bundle: zip `data/` + `data.js` as `ledger-data.zip` in the repo root (gitignored) and send it.

## Model
- Card accounts use post date (matches EveryDollar's month assignment); bank accounts use posting date.
- Categories = EveryDollar items with `group`; kind: Income group -> income, Savings group -> fund, Card Payments -> transfer, else spend.
- Plans: `config.budgets[YYYY-MM][item]`; a month without a plan uses the latest earlier plan.
- Savings view: total = actual balance of `config.savings.account`; bucket = `start` + deposits categorized to the bucket id; Unassigned = remainder.
  Retirement column (HSA/401k/Roth) is manual balances for now.
- `amount`: raw sign from the bank (negative = money out).
- `flow`: budget view. Same as amount, except in a fund-linked account (`"fund"` in config accounts) where non-income activity is a contribution (`flow = -amount`).
- Transfers between tracked accounts and card payments are category `transfer` and excluded from totals.
