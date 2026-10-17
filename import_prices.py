"""Bulk price import.  python3 import_prices.py prices.csv [--apply]
CSV columns: sku_id, price_inr, retailer, url, observed_date (YYYY-MM-DD), note(optional)
Rejects: unknown SKU, price outside 15,000-600,000, missing url/date, future date. Never touches spec columns."""
import csv, sys
from datetime import date
import api, recommendation_engine as R

def main(path, apply):
    skus = {l["sku_id"] for l in R.load_laptops()}
    ok, bad = [], []
    for n, r in enumerate(csv.DictReader(open(path, encoding="utf-8-sig")), 2):
        e = []
        if r.get("sku_id") not in skus: e.append("unknown SKU")
        try: p = float(str(r.get("price_inr", "")).replace(",", "").replace("₹", ""))
        except ValueError: p = None
        if p is None or not 15000 <= p <= 600000: e.append("price missing or outside 15,000-600,000")
        if not (r.get("url") or "").startswith("http"): e.append("url required")
        d = (r.get("observed_date") or "").strip()
        if not d or d > str(date.today()): e.append("observed_date missing or in the future")
        (bad if e else ok).append((n, r, p, e))
    for n, r, _, e in bad: print(f"line {n} {r.get('sku_id')}: " + "; ".join(e))
    print(f"{len(ok)} valid, {len(bad)} rejected")
    if apply:
        for _, r, p, _ in ok: api.save_price(r["sku_id"], p, r.get("retailer"), r["url"], r["observed_date"], r.get("note") or None)
        print("saved", len(ok))

if __name__ == "__main__": main(sys.argv[1], "--apply" in sys.argv)
