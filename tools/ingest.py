#!/usr/bin/env python3
"""Merge bank CSV exports into data/transactions.csv and rebuild data.js.

Usage:
  python3 -I tools/ingest.py [export.csv ...]   # merge files (if any), then rebuild
  python3 -I tools/ingest.py --report           # rebuild and list uncategorized rows

EveryDollar exports (MM-YYYY-EveryDollar-BudgetItems.csv / -Transactions.csv) can be passed
alongside bank files: BudgetItems sets that month's plan and categories, Transactions sets
per-transaction categories by matching account, amount and date.

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
            out.append(dict(date=parse_date(r["Post Date"]), account=acct, description=r["Description"].strip(),
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
            out.append(dict(date=parse_date(r["Posted Date"]), account="capone-card", description=r["Description"].strip(),
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


ED_ACCOUNTS = {"TOTAL CHECKING *7373": "chase-7373", "CREDIT CARD *1291": "chase-1291", "Quicksilver *3047": "capone-card",
               "360 Checking *7035": "360-7035", "360 Performance Savings *8028": "360-8028"}


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def kind_for(group, item):
    if group == "Income":
        return "income"
    if group == "Savings":
        return "fund"
    if item == "Card Payments":
        return "transfer"
    return "spend"


def is_everydollar(path):
    with open(path, newline="", encoding="utf-8-sig") as f:
        head = f.readline()
    return head.startswith('"Group","Item"')


def import_everydollar(paths, cfg):
    """BudgetItems -> categories + monthly plan. Transactions -> per-transaction overrides,
    matched to ledger rows by account, amount and date within 5 days (EveryDollar uses post dates)."""
    cats = {c["id"]: c for c in cfg["categories"]}
    budgets = cfg.setdefault("budgets", {})
    overrides = load_json("overrides.json", {})
    ledger = load_ledger()
    taken = set(overrides)
    for p in sorted(paths, key=lambda x: "Transactions" in Path(x).name):  # budgets first
        m = re.search(r"(\d{2})-(\d{4})", Path(p).name)
        if not m:
            raise SystemExit(f"{Path(p).name}: EveryDollar file needs MM-YYYY in the name")
        month = f"{m.group(2)}-{m.group(1)}"
        with open(p, newline="", encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        if "Planned" in rows[0]:
            plan = {}
            for r in rows:
                cid = slug(r["Item"])
                if cid not in cats:
                    cats[cid] = {"id": cid, "name": r["Item"], "group": r["Group"], "kind": kind_for(r["Group"], r["Item"])}
                plan[cid] = money(r["Planned"])
            budgets[month] = plan
            print(f"{Path(p).name}: plan for {month}, {len(plan)} items")
            continue
        matched, missed = 0, []
        for r in rows:
            cid = slug(r["Item"])
            if cid not in cats:
                cats[cid] = {"id": cid, "name": r["Item"], "group": r["Group"], "kind": kind_for(r["Group"], r["Item"])}
            amt, acct = money(r["Amount"]), ED_ACCOUNTS.get(r["Account"].strip())
            d0 = datetime.strptime(r["Date"], "%m/%d/%Y")
            best = None
            for t in ledger:
                if t["id"] in taken or abs(float(t["amount"]) - amt) > 0.005 or (acct and t["account"] != acct):
                    continue
                gap = abs((datetime.strptime(t["date"], "%Y-%m-%d") - d0).days)
                if gap <= 5 and (best is None or gap < best[0]):
                    best = (gap, t)
            if best:
                overrides[best[1]["id"]] = cid
                taken.add(best[1]["id"])
                matched += 1
            else:
                missed.append((r, acct, amt, cid))
        # Splits: several EveryDollar rows on one date/account that sum to one bank row.
        groups = {}
        for r, acct, amt, cid in missed:
            groups.setdefault((r["Date"], acct), []).append((r, amt, cid))
        still = []
        for (date, acct), parts in groups.items():
            total = round(sum(a for _, a, _ in parts), 2)
            d0 = datetime.strptime(date, "%m/%d/%Y")
            hit = next((t for t in ledger if t["id"] not in taken and abs(float(t["amount"]) - total) < 0.005
                        and (not acct or t["account"] == acct) and len(parts) > 1
                        and abs((datetime.strptime(t["date"], "%Y-%m-%d") - d0).days) <= 5), None)
            if hit:
                overrides[hit["id"]] = [[cid, a] for _, a, cid in parts]
                taken.add(hit["id"])
                matched += len(parts)
            else:
                still += [f"{r['Date']} {r['Merchant']} {a:.2f} [{r['Account'] or '?'}] -> {r['Item']}" for r, a, _ in parts]
        print(f"{Path(p).name}: {matched}/{len(rows)} matched to bank rows")
        for x in still:
            print("  not in bank data:", x)
    # keep config order: by group order of first appearance, transfer/other last
    cfg["categories"] = list(cats.values())
    save_json("overrides.json", overrides)
    save_json("config.json", cfg)


def categorize(r, rules, overrides, cfg, kinds):
    """Return (category, flow). flow is the amount from the budget's point of view:
    negative = money leaving the spending pool (spend or saved), positive = income/refund."""
    amt = float(r["amount"])
    fund = cfg["accounts"].get(r["account"], {}).get("fund")
    day = int(r["date"][8:])
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
            elif fund and kinds.get(rule["cat"]) != "income":
                continue
            if "amount" in rule and abs(rule["amount"] - amt) > 0.005:
                continue
            if not rule.get("day_from", 1) <= day <= rule.get("day_to", 31):
                continue
            if re.search(rule["match"], r["description"], re.I):
                cat = rule["cat"]
                break
        if cat is None and fund:
            cat = fund
    if fund and kinds.get(cat) == "fund":
        # deposits are contributions (leave the spending pool), withdrawals reduce the fund
        return cat, -amt
    return cat, amt


def build(cfg, report=False):
    rules = load_json("rules.json", [])
    overrides = load_json("overrides.json", {})
    balances = load_json("balances.json", {})
    kinds = {c["id"]: c["kind"] for c in cfg["categories"]}
    for rule in rules:
        if rule["cat"] not in kinds:
            raise SystemExit(f"rules.json: unknown category {rule['cat']!r}")
    tx = []
    for r in load_ledger():
        ov = overrides.get(r["id"])
        if isinstance(ov, list):  # split: [[cat, amount], ...]
            for i, (c, a) in enumerate(ov, 1):
                sub = dict(r, id=f"{r['id']}-{i}", amount=f"{a:.2f}")
                cat, flow = categorize(sub, rules, {sub["id"]: c}, cfg, kinds)
                tx.append(dict(id=sub["id"], date=r["date"], account=r["account"], desc=clean_desc(r["description"]) + f" (split {i}/{len(ov)})",
                               raw=r["description"], amount=a, flow=round(flow, 2), cat=cat, card=r["card"], src="manual"))
            continue
        cat, flow = categorize(r, rules, overrides, cfg, kinds)
        tx.append(dict(id=r["id"], date=r["date"], account=r["account"], desc=clean_desc(r["description"]),
                       raw=r["description"], amount=float(r["amount"]), flow=round(flow, 2), cat=cat, card=r["card"],
                       src="manual" if r["id"] in overrides else "rule" if cat else None))
    accounts = [dict(id=k, **v, **balances.get(k, {})) for k, v in cfg["accounts"].items()]
    last = max((t["date"] for t in tx), default=None)
    payload = dict(generated=datetime.now().strftime("%Y-%m-%d %H:%M"), start=cfg["start_date"], last=last,
                   accounts=accounts, categories=cfg["categories"], budgets=cfg.get("budgets", {}),
                   savings=cfg.get("savings", {}), tx=tx)
    (ROOT / "data.js").write_text("window.LEDGER = " + json.dumps(payload, separators=(",", ":")) + ";\n")
    unc = [t for t in tx if not t["cat"]]
    print(f"data.js: {len(tx)} transactions {cfg['start_date']}..{last}, {len(unc)} uncategorized")
    if report:
        for t in unc:
            print(f"  {t['id']}  {t['date']}  {t['account']:<12} {t['amount']:>10.2f}  {t['desc']}")
        groups = {c["id"]: c.get("group", c["id"]) for c in cfg["categories"]}
        months = {}
        for t in tx:
            if kinds.get(t["cat"]) == "transfer":
                continue
            g = groups.get(t["cat"], "UNCAT")
            m = months.setdefault(t["date"][:7], {})
            m[g] = round(m.get(g, 0) - t["flow"], 2)
        for m in sorted(months):
            print(m, json.dumps(months[m]))


def main(argv):
    report = "--report" in argv
    paths = [a for a in argv if not a.startswith("--")]
    cfg = load_json("config.json", None)
    if cfg is None:
        raise SystemExit("data/config.json missing (restore it from the artifact, see CLAUDE.md)")
    ed = [p for p in paths if is_everydollar(p)]
    bank = [p for p in paths if p not in ed]
    if bank:
        merge(bank, cfg)
    if ed:
        import_everydollar(ed, cfg)
    build(cfg, report)


if __name__ == "__main__":
    main(sys.argv[1:])
