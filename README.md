# Ledger Board

Single-file, offline personal finance board. Open `index.html` in a browser; no build, no server.

- **Monthly waterfall**: income stepped down by each category and fund; dashed outline = budget, red = over budget.
- **Budget categories**: hatched fill = spent vs budget. Budgets are editable in place.
- **Transactions**: drag a row onto a category (or click row, then click category, or use the dropdown). Each assignment saves a payee rule and auto-applies it to matching rows.
- **Funds**: Savings / 401k / Vacation / Vitamins etc. as fill-to-goal bars; fees shown as a hatched band.

## CSV import
Drop one or more bank CSV exports on the page (or use Import CSV). Headers are auto-detected:
`Date` (YYYY-MM-DD or MM/DD/YYYY), `Description`/`Payee`/`Memo`, and either `Amount` (negative = outflow) or `Debit` + `Credit`.
Re-importing the same file skips duplicates. All data persists in browser localStorage only. Export writes a categorized CSV.

Starts with clearly-marked sample data; the first import replaces it. Reset restores the sample.
