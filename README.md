# Ledger Board

Offline personal finance board: monthly waterfall, budget categories, transaction categorization, account balances and fund goals.

```
python3 -I tools/ingest.py path/to/exports/*.csv   # merge exports into data/ and build data.js
open index.html
```

Supported exports (detected by header): Chase checking, Chase credit card (filename must contain `Chase####`), Capital One card, Capital One 360 checking/savings. Overlapping exports are deduplicated. Categorization is regex rules in `data/rules.json` plus per-transaction overrides in `data/overrides.json`; budgets, accounts and start date live in `data/config.json`.

`data/` and `data.js` hold personal data and are gitignored. See CLAUDE.md for the update workflow.
