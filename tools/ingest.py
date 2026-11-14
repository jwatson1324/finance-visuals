#!/usr/bin/env python3
"""Merge bank CSV exports into data/transactions.csv and rebuild data.js.

Usage:
  python3 -I tools/ingest.py [export.csv ...]   # merge files (if any), then rebuild
  python3 -I tools/ingest.py --report           # rebuild and list uncategorized rows

Supported formats (detected by header):
  Chase credit card   Transaction Date,Post Date,Description,Category,Type,Amount,Memo
  Chase checking      Details,Posting Date,Description,Amount,Type,Balance,Check or Slip #
  Capital One card    Transaction Date,Posted Date,Card No.,Description,Category,Debit,Credit
  Capital One 360     Account Number,Transaction Description,Transaction Date,Transaction Type,Transaction Amount,Balance

Chase exports carry the last 4 digits only in the filename (Chase1291_Activity_...).
Re-importing overlapping exports is safe: rows are deduplicated by
(account, date, raw description, amount, occurrence count).
"""
import csv, hashlib, json, re, sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
LEDGER = DATA / "transactions.csv"
FIELDS = ["id", "date", "account", "description", "amount", "card", "bank_category"]


def load_json(name, default):
    p = DATA / name
    return json.loads(p.read_text()) if p.exists() else default


def save_json(name, obj):
    (DATA / name).write_text(json.dumps(obj, indent=2) + "\n")


def parse_date(s):
    s = s.strip()
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"unrecognized date: {s!r}")


def money(s):
    s = (s or "").strip().replace(",", "").replace("$", "")
    return float(s) if s else 0.0


def read_export(path):
    """Yield normalized rows: dict(date, account, description, amount, card, bank_category, balance)."""
    path = Path(path)
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    rows = [r for r in rows if any(c.strip() for c in r)]
    if not rows:
        return []
    h = [c.strip() for c in rows[0]]
    body = [dict(zip(h, r)) for r in rows[1:]]
    out = []
    m4 = re.search(r"chase\s*(\d{4})", path.name, re.I)

    if h[:3] == ["Transaction Date", "Post Date", "Description"]:
        if not m4:
            raise SystemExit(f"{path.name}: Chase card export, but no last-4 in filename (expected Chase####_...)")
        acct = f"chase-{m4.group(1)}"
        for r in body:
            out.append(dict(date=parse_date(r["Transaction Date"]), account=acct, description=r["Description"].strip(),
                            amount=money(r["Amount"]), card="", bank_category=r.get("Category", "").strip(), balance=None))
    elif h[:2] == ["Details", "Posting Date"]:
        if not m4:
            raise SystemExit(f"{path.name}: Chase checking export, but no last-4 in filename (expected Chase####_...)")
        acct = f"chase-{m4.group(1)}"
        for r in body:
            bal = r.get("Balance", "").strip()
            out.append(dict(date=parse_date(r["Posting Date"]), account=acct, description=r["Description"].strip(),
                            amount=money(r["Amount"]), card="", bank_category=r.get("Type", "").strip(),
                            balance=money(bal) if bal else None))
    elif "Card No." in h and "Debit" in h and "Credit" in h:
        for r in body:
            out.append(dict(date=parse_date(r["Transaction Date"]), account="capone-card", description=r["Description"].strip(),
                            amount=round(money(r["Credit"]) - money(r["Debit"]), 2), card=r["Card No."].strip(),
                            bank_category=r.get("Category", "").strip(), balance=None))
    elif h[:2] == ["Account Number", "Transaction Description"]:
        for r in body:
            amt = money(r["Transaction Amount"])
            if r["Transaction Type"].strip().lower() == "debit":
                amt = -abs(amt)
            bal = r.get("Balance", "").strip()
            out.append(dict(date=parse_date(r["Transaction Date"]), account=f"360-{r['Account Number'].strip()}",
                            description=r["Transaction Description"].strip(), amount=amt, card="",
                            bank_category=r["Transaction Type"].strip(), balance=money(bal) if bal else None))
    else:
        raise SystemExit(f"{path.name}: unrecognized CSV header: {','.join(h)}")
    return out


def base_key(r):
    return f"{r['account']}|{r['date']}|{r['description']}|{float(r['amount']):.2f}"


def load_ledger():
    if not LEDGER.exists():
        return []
    with LEDGER.open(newline="") as f:
        return list(csv.DictReader(f))


def merge(paths, cfg):
    ledger = load_ledger()
    have = {}
    for r in ledger:
        have[base_key(r)] = have.get(base_key(r), 0) + 1
    balances = load_json("balances.json", {})
    start = cfg["start_date"]
    added_total = 0
    for p in paths:
        rows = read_export(p)
        seen, added = {}, 0
        # balance: latest dated row; exports list newest first, so first row wins ties
        latest = {}
        for r in rows:
            if r["balance"] is not None and (r["account"] not in latest or r["date"] > latest[r["account"]]["date"]):
                latest[r["account"]] = r
        for acct, r in latest.items():
            if acct not in balances or r["date"] >= balances[acct]["as_of"]:
                balances[acct] = {"balance": r["balance"], "as_of": r["date"]}
        for r in rows:
            if r["date"] < start:
                continue
            k = base_key(r)
            seen[k] = seen.get(k, 0) + 1
            if seen[k] <= have.get(k, 0):
                continue
            have[k] = have.get(k, 0) + 1
            rid = hashlib.sha1(f"{k}|{seen[k]}".encode()).hexdigest()[:10]
            ledger.append(dict(id=rid, date=r["date"], account=r["account"], description=r["description"],
                               amount=f"{r['amount']:.2f}", card=r["card"], bank_category=r["bank_category"]))
            added += 1
            if r["account"] not in cfg["accounts"]:
                cfg["accounts"][r["account"]] = {"name": r["account"], "short": r["account"], "type": "checking"}
                print(f"  new account {r['account']}: add a name in data/config.json")
        print(f"{Path(p).name}: {len(rows)} rows, {added} new")
        added_total += added
    ledger = [r for r in ledger if r["date"] >= start]
    ledger.sort(key=lambda r: (r["date"], r["account"], r["id"]))
    with LEDGER.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(ledger)
    save_json("balances.json", balances)
    save_json("config.json", cfg)
    return added_total


def clean_desc(s):
    s = re.sub(r"\s+(PPD|WEB) ID:\s*\S+", "", s)
    s = re.sub(r"\s+transaction#:.*$", "", s)
    s = re.sub(r"\s+\d{2}/\d{2}$", "", s)
    s = re.sub(r"^Withdrawal from |^Deposit from |^Debit Card Purchase - ", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def categorize(r, rules, overrides, cfg):
    """Return (category, flow). flow is the amount from the budget's point of view:
    negative = money leaving the spending pool (spend or saved), positive = income/refund."""
    amt = float(r["amount"])
    fund = cfg["accounts"].get(r["account"], {}).get("fund")
    if r["id"] in overrides:
        cat = overrides[r["id"]]
    else:
        cat = None
        for rule in rules:
            # In a fund-linked account only account-scoped rules and income rules apply;
            # everything else there is a contribution to / withdrawal from the fund.
            if rule.get("account"):
                if rule["account"] != r["account"]:
                    continue
            elif fund and rule["cat"] != "income":
                continue
            if re.search(rule["match"], r["description"], re.I):
                cat = rule["cat"]
                break
    if fund and cat not in ("income", "transfer"):
        # deposits are contributions (leave the spending pool), withdrawals reduce the fund
        return fund, -amt
    return cat, amt


def build(cfg, report=False):
    rules = load_json("rules.json", [])
    overrides = load_json("overrides.json", {})
    balances = load_json("balances.json", {})
    tx = []
    for r in load_ledger():
        cat, flow = categorize(r, rules, overrides, cfg)
        tx.append(dict(id=r["id"], date=r["date"], account=r["account"], desc=clean_desc(r["description"]),
                       raw=r["description"], amount=float(r["amount"]), flow=round(flow, 2), cat=cat, card=r["card"]))
    accounts = [dict(id=k, **v, **balances.get(k, {})) for k, v in cfg["accounts"].items()]
    last = max((t["date"] for t in tx), default=None)
    payload = dict(generated=datetime.now().strftime("%Y-%m-%d %H:%M"), start=cfg["start_date"], last=last,
                   accounts=accounts, categories=cfg["categories"], tx=tx)
    (ROOT / "data.js").write_text("window.LEDGER = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    unc = [t for t in tx if not t["cat"]]
    print(f"data.js: {len(tx)} transactions {cfg['start_date']}..{last}, {len(unc)} uncategorized")
    if report:
        for t in unc:
            print(f"  {t['id']}  {t['date']}  {t['account']:<12} {t['amount']:>10.2f}  {t['desc']}")
        months = {}
        for t in tx:
            c = t["cat"] or "UNCAT"
            if c == "transfer":
                continue
            m = months.setdefault(t["date"][:7], {})
            m[c] = round(m.get(c, 0) - t["flow"], 2)
        for m in sorted(months):
            print(m, json.dumps(dict(sorted(months[m].items()))))


def main(argv):
    report = "--report" in argv
    paths = [a for a in argv if not a.startswith("--")]
    cfg = load_json("config.json", None)
    if cfg is None:
        raise SystemExit("data/config.json missing (restore it from the artifact, see CLAUDE.md)")
    if paths:
        merge(paths, cfg)
    build(cfg, report)


if __name__ == "__main__":
    main(sys.argv[1:])
