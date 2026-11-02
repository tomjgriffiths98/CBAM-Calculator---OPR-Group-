#!/usr/bin/env python3
"""Refresh docs/data.json, the data behind the CBAM calculator web page.

  python update_data.py                       # live prices only: UK rate (GOV.UK) + EU carbon price
  python update_data.py --calculator-xlsx "CBAM UK AND EU CALCULATOR.xlsx" \
                        --defaults-xlsx  "Default Values Per Commodity Code NEW.xlsx"
                                             # also refresh mills and default values from the workbooks
  python update_data.py --dry-run            # show what would change, write nothing

Rules: it only ever writes numbers it has read from a source, it never guesses, and if a page
cannot be parsed it leaves the old value in place and reports a warning (exit code 2).
"""
import argparse, json, re, sys, datetime as dt
from pathlib import Path

DATA = Path(__file__).parent / "docs" / "data.json"
UK_RATE_URL = ("https://www.gov.uk/government/publications/illustrative-cbam-rates-and-worked-example-for-"
               "carbon-border-adjustment-mechanism-cbam/carbon-border-adjustment-mechanism-cbam-"
               "illustrative-cbam-rates-and-worked-example")
EU_LIVE_URL = "https://www.purelyenergy.co.uk/tools/carbon/eu-ets"
HEADERS = {"User-Agent": "Mozilla/5.0 (OPR CBAM calculator updater)"}
WARNINGS = []


def now_utc():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def warn(msg):
    WARNINGS.append(msg)
    print("WARNING:", msg, file=sys.stderr)


def fetch_text(url):
    import requests
    from bs4 import BeautifulSoup
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    for t in soup(["script", "style", "noscript"]):
        t.decompose()
    return soup


# ---------------------------------------------------------------- UK rate (GOV.UK)
MONTHS = {m: i + 1 for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
     "November", "December"])}


def parse_uk_rate(soup):
    """Return dict(rate, quarter_start, published) from the GOV.UK illustrative rates page, or None."""
    rate = None
    for tr in soup.select("table tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["th", "td"])]
        if cells and re.search(r"iron\s*(and|&)\s*steel", cells[0], re.I):
            for c in cells[1:]:
                m = re.search(r"£\s*([0-9]+(?:\.[0-9]+)?)", c) or re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)", c)
                if m:
                    rate = float(m.group(1))
                    break
            if rate is not None:
                break
    if rate is None or not (0 < rate < 100):
        return None
    text = soup.get_text("\n", strip=True)
    qs = re.search(r"1 (January|April|July|October) (20\d\d)", text)
    quarter_start = f"{qs.group(2)}-{MONTHS[qs.group(1)]:02d}-01" if qs else None
    pub = re.search(r"(?:Published|First published)\s*\n?\s*(\d{1,2}) (\w+) (20\d\d)", text)
    published = None
    if pub and pub.group(2) in MONTHS:
        published = f"{pub.group(3)}-{MONTHS[pub.group(2)]:02d}-{int(pub.group(1)):02d}"
    return {"rate": rate, "quarter_start": quarter_start, "published": published}


def update_uk_rate(data):
    try:
        info = parse_uk_rate(fetch_text(UK_RATE_URL))
    except Exception as e:  # network or parse problem
        warn(f"UK rate: could not read GOV.UK ({e}); rate left unchanged")
        info = None
    meta = data["docs"].setdefault("meta/uk_rate_check", {})
    meta["checkedAt"] = now_utc()
    if not info:
        if info is None:
            warn("UK rate: iron and steel figure not found on the GOV.UK page; rate left unchanged")
        meta["note"] = "Could not read the GOV.UK page; rate unchanged."
        return
    rates = data["collections"].setdefault("uk_rates", {})
    start = info["quarter_start"] or (max(rates.values(), key=lambda r: r["periodStart"])["periodStart"] if rates else None)
    if not start:
        warn("UK rate: no quarter found; not written")
        return
    y, m = int(start[:4]), int(start[5:7])
    qid = f"{y}-Q{(m - 1) // 3 + 1}"
    cur = rates.get(qid)
    if cur and abs(cur["rate"] - info["rate"]) > 0.0049:
        if abs(info["rate"] - cur["rate"]) / cur["rate"] > 0.5:
            warn(f"UK rate: {qid} would change {cur['rate']} -> {info['rate']} (>50%); not written, please check")
            meta["note"] = "Large change found; not written, needs a person to check."
            return
        cur.update({"previousRate": cur["rate"], "previousStatus": cur.get("status"), "changedOn": dt.date.today().isoformat(),
                    "rate": info["rate"], "publishedOn": info["published"] or cur.get("publishedOn"), "sourceUrl": UK_RATE_URL})
        meta["note"] = f"{qid} rate changed to {info['rate']}."
        print(f"UK rate: {qid} changed to {info['rate']}")
    elif not cur:
        rates[qid] = {"quarter": f"Q{(m - 1) // 3 + 1} {y}", "periodStart": start, "rate": info["rate"],
                      "status": "illustrative", "basis": "See GOV.UK page", "publishedOn": info["published"] or "",
                      "sourceUrl": UK_RATE_URL}
        meta["note"] = f"Added {qid} rate of {info['rate']}. Check status (illustrative or actual) and basis."
        warn(f"UK rate: new quarter {qid} added at {info['rate']}; set status/basis in data.json if it is an actual rate")
    else:
        meta["note"] = f"No change, {qid} rate {cur['rate']} matches GOV.UK."
        print("UK rate: no change", qid, cur["rate"])


# ---------------------------------------------------------------- EU carbon price (Purely Energy)
def parse_eu_live(soup):
    text = soup.get_text("\n", strip=True)
    label = re.search(r"Settlement\s+\w+day\s+\d{1,2}\s+\w+\s+\d{4}", text)
    price = None
    for m in re.finditer(r"(?:€|EUR)\s*([0-9]{2,3}(?:\.[0-9]{1,2})?)", text):
        v = float(m.group(1))
        if 10 <= v <= 300:
            price = v
            break
    if price is None:
        return None
    return {"price": price, "label": label.group(0) if label else ""}


def update_eu_live(data):
    doc = data["docs"].setdefault("meta/eu_live", {"sourceUrl": EU_LIVE_URL})
    doc["checkedAt"] = now_utc()
    try:
        info = parse_eu_live(fetch_text(EU_LIVE_URL))
    except Exception as e:
        warn(f"EU price: could not read Purely Energy ({e}); price left unchanged")
        return
    if not info:
        warn("EU price: no plausible euro price found on the page; price left unchanged")
        return
    doc.update({"price": info["price"], "label": info["label"] or doc.get("label", ""), "sourceUpdatedAt": now_utc()})
    print("EU price:", info["price"], info["label"])


# ---------------------------------------------------------------- workbooks (run locally)
def _num(v):
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def read_mills(xlsx):
    import openpyxl
    vals, fml = openpyxl.load_workbook(xlsx, data_only=True), openpyxl.load_workbook(xlsx, data_only=False)
    uk, eu = [], []
    ws = vals.worksheets[0]
    for r in range(4, ws.max_row + 1):
        mill, prod, em, safety = (ws.cell(r, c).value for c in (1, 2, 3, 5))
        if _num(em) is None:
            continue
        uk.append({"mill": str(mill or "").strip(), "product": str(prod or "").strip(), "em": _num(em),
                   "safety": _num(safety) if _num(safety) is not None else 0.25})
    ws, wf = vals.worksheets[1], fml.worksheets[1]
    for r in range(4, ws.max_row + 1):
        mill, prod, em, sefa = (ws.cell(r, c).value for c in (1, 2, 4, 6))
        if _num(em) is None:
            continue
        raw = wf.cell(r, 6).value
        flag = None
        if isinstance(raw, str) and raw.startswith("=") and not _num(sefa):
            flag = "formula"
        elif not _num(sefa):
            flag = "zero"
        eu.append({"mill": str(mill or "").strip(), "product": str(prod or "").strip(), "em": _num(em),
                   "sefa": _num(sefa) or 0, "flag": flag})
    return uk, eu


def _key(x):
    return (x["mill"].lower(), x["product"].lower())


def carry_added(new, old):
    today = dt.date.today().isoformat()
    old_by = {_key(o): o for o in old}
    for n in new:
        o = old_by.get(_key(n))
        if o is None:
            n["added"] = today
        elif o.get("added"):
            n["added"] = o["added"]
    return [(_key(o)) for o in old if _key(o) not in {_key(n) for n in new}]


def update_mills(data, xlsx):
    uk, eu = read_mills(xlsx)
    if len(uk) < 10 or len(eu) < 10:
        warn("Mills: fewer than 10 lines read; not written")
        return
    old = data["docs"].get("meta/mills", {"uk": [], "eu": []})
    gone = carry_added(uk, old.get("uk", [])) + carry_added(eu, old.get("eu", []))
    n_new = sum(1 for x in uk + eu if x.get("added") == dt.date.today().isoformat())
    data["docs"]["meta/mills"] = {"uk": uk, "eu": eu, "checkedAt": now_utc(),
                                  "note": f"{len(uk)} UK and {len(eu)} EU lines from the workbook; {n_new} new."}
    print(f"Mills: {len(uk)} UK / {len(eu)} EU lines, {n_new} new, {len(gone)} removed")


def read_defaults(xlsx):
    import openpyxl
    ws = openpyxl.load_workbook(xlsx, data_only=True).worksheets[0]
    source_line = next((str(ws.cell(r, 1).value) for r in range(1, 9) if str(ws.cell(r, 1).value or "").startswith("Default values source")), "")
    hdr = next(r for r in range(1, 20) if str(ws.cell(r, 1).value or "").startswith("OPR product code"))
    rows = []
    for r in range(hdr + 1, ws.max_row + 1):
        v = [ws.cell(r, c).value for c in range(1, 10)]
        if not v[0]:
            continue
        rows.append({"code": str(v[0]).strip(), "product": str(v[1] or "").strip(), "desc": str(v[2] or "").strip(),
                     "comm": str(v[3] or "").strip(), "cn": str(v[4] or "").strip(), "status": str(v[5] or "").strip(),
                     "dv": _num(v[6]), "notes": str(v[8] or "").strip()})
    return rows, source_line


def update_defaults(data, xlsx):
    rows, source_line = read_defaults(xlsx)
    if len(rows) < 20:
        warn("Defaults: fewer than 20 rows read; not written")
        return
    old = data["docs"].get("meta/defaults", {}).get("rows", [])
    today = dt.date.today().isoformat()
    key = lambda x: (x["comm"], x["code"])
    old_by = {key(o): o for o in old}
    changed = added = 0
    for n in rows:
        o = old_by.get(key(n))
        if o is None:
            n["added"] = today; added += 1
        else:
            same = all(o.get(f) == n[f] for f in ("dv", "status", "notes", "desc", "product", "cn"))
            if o.get("added"): n["added"] = o["added"]
            if same and o.get("updated"): n["updated"] = o["updated"]
            if not same: n["updated"] = today; changed += 1
    data["docs"]["meta/defaults"] = {"rows": rows, "sourceLine": source_line, "checkedAt": now_utc(),
                                     "note": f"{len(rows)} codes from the workbook; {changed} changed, {added} new."}
    print(f"Defaults: {len(rows)} rows, {changed} changed, {added} new")


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--calculator-xlsx")
    ap.add_argument("--defaults-xlsx")
    ap.add_argument("--skip-web", action="store_true", help="do not fetch GOV.UK / Purely Energy")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    data = json.loads(DATA.read_text(encoding="utf-8"))
    before = json.dumps(data, sort_keys=True)
    if not a.skip_web:
        update_uk_rate(data)
        update_eu_live(data)
    if a.calculator_xlsx:
        update_mills(data, a.calculator_xlsx)
    if a.defaults_xlsx:
        update_defaults(data, a.defaults_xlsx)
    after = json.dumps(data, sort_keys=True)
    if a.dry_run:
        print("dry run: nothing written")
    else:
        DATA.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        print("data.json written" if before != after else "data.json unchanged")
    sys.exit(2 if WARNINGS else 0)


if __name__ == "__main__":
    main()
