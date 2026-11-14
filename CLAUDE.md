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
3. `python3 -I tools/ingest.py data/inbox/<files> --report` (dedupes overlaps; drops rows before `start_date`).
4. For each uncategorized row, add or extend a regex in `data/rules.json` (preferred) or set `data/overrides.json` `{txId: catId}`; rerun with `--report` until 0 uncategorized. Sanity-check monthly totals in the report.
5. If the user pasted "Ledger Board changes" JSON from the page: put `overrides` into `data/overrides.json` (cat values only), `budgets` into `data/config.json` category budgets, `funds` balance/goal into the fund categories. Suggest a rule when several rows share a payee.
6. Republish: strip the outer `<!doctype>/<html>/<head>/<body>` tags from `index.html` into the scratchpad, and publish to the artifact URL above with `files` = data.js + `ledger/*` from `data/`.
7. Commit only code changes (`index.html`, `tools/`, docs).

## Model
- `amount`: raw sign from the bank (negative = money out).
- `flow`: budget view. Same as amount, except in a fund-linked account (`"fund"` in config accounts) where non-income activity is a contribution (`flow = -amount`).
- Transfers between tracked accounts and card payments are category `transfer` and excluded from totals.
