# Local setup prompt

Download `ledger-data.zip` from the Claude session, then paste the block below into Claude Code
running on your machine (edit the zip path if it is not in Downloads).

```
Set up my Ledger Board finance app locally. Personal finance data must never be committed or pushed;
the GitHub repo is public.

1. Clone https://github.com/jwatson1324/finance-visuals (or cd into my existing clone), then
   git fetch origin claude/gifted-brahmagupta-ow122i && git checkout claude/gifted-brahmagupta-ow122i && git pull.
2. Before touching any data:
   - Confirm .gitignore contains: data/, data.js, *.csv, ledger-data*.zip
   - Append the same four lines to .git/info/exclude (local-only ignore, survives .gitignore edits)
   - cp tools/pre-commit .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
3. Unzip ~/Downloads/ledger-data.zip into the repo root so that data/ and data.js exist there.
   Then delete the zip, or move it outside the repo.
4. Verify nothing is trackable:
   - git check-ignore -v data/transactions.csv data/config.json data.js   (each line must print a match)
   - git status --porcelain --ignored   (data/ and data.js listed only under "!!")
   Stop and tell me if any data file shows as untracked or staged.
5. Run: python3 tools/ingest.py --report
   Expect "225 transactions 2026-09-01..2026-11-14, 3 uncategorized".
6. Open index.html in a browser.
7. Read CLAUDE.md for the update workflow. Never use git add -f, git add -A on data paths, or
   --no-verify. Only commit index.html, tools/, and docs.
```
