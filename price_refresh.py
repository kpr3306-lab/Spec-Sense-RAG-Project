"""
SpecSense — Live price refresh pipeline (Google Custom Search JSON API, free tier).

Per the blueprint's own data-quality rule (§10): "Refresh prices, availability and
service information separately from relatively stable hardware specifications."
This script ONLY touches the live-pricing columns added below — it never touches
CPU/GPU/RAM/display/etc. Those stay as verified-once structured specs.

New columns this adds to `laptops` (idempotent — safe to run ALTER multiple times):
    observed_price_inr       - best price figure parsed from a live web result
    price_source_url         - the search result page the price was parsed from
    retailer_name             - domain of that source (e.g. 'amazon.in')
    price_last_checked_date  - ISO date this row was last refreshed
    live_availability_note   - free-text note, e.g. "no price found in top results"

-----------------------------------------------------------------------------
SETUP (you do this once, outside this sandbox, with your own free Google account)
-----------------------------------------------------------------------------
1. Go to https://console.cloud.google.com/ -> create/select a project ->
   enable "Custom Search API" -> Credentials -> Create API key.
   This is GOOGLE_API_KEY.
2. Go to https://programmablesearchengine.google.com/ -> Add a new search engine
   -> set it to search the entire web -> copy its "Search engine ID".
   This is GOOGLE_CSE_ID.
3. Free tier: 100 queries/day. This script does one query per laptop (28 total),
   so a full refresh comfortably fits in a single day's free quota.
4. Set the two values as environment variables before running:
       export GOOGLE_API_KEY="your-key-here"
       export GOOGLE_CSE_ID="your-cse-id-here"
   (On Windows: set GOOGLE_API_KEY=... / set GOOGLE_CSE_ID=...)

-----------------------------------------------------------------------------
IMPORTANT CAVEAT — read before trusting the output
-----------------------------------------------------------------------------
The Custom Search API returns web search results (title + snippet text), NOT a
structured product-price field the way a dedicated shopping API would. This
script parses ₹ amounts out of that free text with a regex and a plausibility
range (₹15,000-₹500,000 for a laptop) — it can occasionally pick up the wrong
number (an accessory bundled in the same listing, a crossed-out "original
price", an unrelated number on the page). Treat `observed_price_inr` as a
rough signal to review, not a verified price — `price_source_url` is included
specifically so a human can double-check it before trusting it.

-----------------------------------------------------------------------------
THIS SANDBOX HAS NO INTERNET ACCESS TO GOOGLE'S API
-----------------------------------------------------------------------------
Run this on your own machine where it has real internet access. Use
`--dry-run` to test the parsing/DB-update logic right now with mocked search
results, with no API key and no network calls at all.
"""

import os
import re
import sqlite3
import time
import argparse
import json
import urllib.request
import urllib.parse
import urllib.error
from datetime import date
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # project root (parent of src/)
DB_PATH = str(BASE_DIR / "data" / "specsense.db")
SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
MIN_PLAUSIBLE_INR = 15000
MAX_PLAUSIBLE_INR = 500000
REQUEST_DELAY_SECONDS = 1.5  # be polite to the free quota / API

PRICE_PATTERN = re.compile(
    r"(?:₹|Rs\.?|INR)\s?([\d][\d,]{3,9})",
    re.IGNORECASE,
)


def ensure_columns():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(laptops)")
    existing = {r[1] for r in cur.fetchall()}
    for col, t in [
        ("observed_price_inr", "REAL"), ("price_source_url", "TEXT"),
        ("retailer_name", "TEXT"), ("price_last_checked_date", "TEXT"),
        ("live_availability_note", "TEXT"),
    ]:
        if col not in existing:
            cur.execute(f"ALTER TABLE laptops ADD COLUMN {col} {t}")
    conn.commit()
    conn.close()


def load_laptops():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT sku_id, brand, model_name, msrp_inr FROM laptops").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def extract_plausible_price(text):
    """Return the first ₹ amount in `text` that falls in a plausible laptop-price range."""
    for match in PRICE_PATTERN.finditer(text or ""):
        raw = match.group(1).replace(",", "")
        try:
            value = int(raw)
        except ValueError:
            continue
        if MIN_PLAUSIBLE_INR <= value <= MAX_PLAUSIBLE_INR:
            return value
    return None


def google_cse_search(query, api_key, cse_id, num=5):
    params = {"key": api_key, "cx": cse_id, "q": query, "num": num, "gl": "in"}
    url = f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="ignore")
        raise RuntimeError(f"Google CSE HTTP {e.code}: {body[:300]}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error reaching Google CSE: {e}") from e


MOCK_RESULTS = {
    # Used only with --dry-run, so the parsing/update logic can be verified with
    # zero network calls and zero API key. Not real prices.
    "default": {
        "items": [
            {"title": "Buy Laptop Online - Flipkart",
             "link": "https://www.flipkart.com/example-laptop",
             "snippet": "Price: ₹74,990. In stock. Free delivery available."},
            {"title": "Laptop - Amazon.in",
             "link": "https://www.amazon.in/example-laptop",
             "snippet": "M.R.P.: ₹82,990 Deal of the Day: ₹76,490 Only 3 left in stock."},
        ]
    }
}


def refresh_one(laptop, api_key, cse_id, dry_run):
    query = f"{laptop['brand']} {laptop['model_name']} price India"
    if dry_run:
        data = MOCK_RESULTS["default"]
    else:
        data = google_cse_search(query, api_key, cse_id)

    items = data.get("items", [])
    for item in items:
        text = f"{item.get('title', '')} {item.get('snippet', '')}"
        price = extract_plausible_price(text)
        if price is not None:
            domain = urllib.parse.urlparse(item.get("link", "")).netloc
            return {
                "observed_price_inr": price,
                "price_source_url": item.get("link"),
                "retailer_name": domain,
                "live_availability_note": None,
            }
    return {
        "observed_price_inr": None,
        "price_source_url": None,
        "retailer_name": None,
        "live_availability_note": "no plausible price found in top search results",
    }


def update_laptop(sku_id, result):
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        UPDATE laptops SET
            observed_price_inr = ?, price_source_url = ?, retailer_name = ?,
            price_last_checked_date = ?, live_availability_note = ?
        WHERE sku_id = ?
    """, (result["observed_price_inr"], result["price_source_url"], result["retailer_name"],
          date.today().isoformat(), result["live_availability_note"], sku_id))
    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(description="Refresh live price fields via Google Custom Search API.")
    parser.add_argument("--dry-run", action="store_true",
                         help="Use mocked search results, no network calls, no API key needed.")
    parser.add_argument("--limit", type=int, default=None,
                         help="Only refresh the first N laptops (useful to conserve free-tier quota).")
    args = parser.parse_args()

    ensure_columns()
    api_key = os.environ.get("GOOGLE_API_KEY")
    cse_id = os.environ.get("GOOGLE_CSE_ID")

    if not args.dry_run and (not api_key or not cse_id):
        print("ERROR: GOOGLE_API_KEY and GOOGLE_CSE_ID must be set (see this file's docstring), "
              "or re-run with --dry-run to test offline.")
        return

    laptops = load_laptops()
    if args.limit:
        laptops = laptops[:args.limit]

    print(f"Refreshing {len(laptops)} laptops "
          f"{'(DRY RUN - mocked data, no network calls)' if args.dry_run else '(live API calls)'}...")

    successes, misses, errors = 0, 0, 0
    log_rows = []
    for i, l in enumerate(laptops, 1):
        try:
            result = refresh_one(l, api_key, cse_id, args.dry_run)
            update_laptop(l["sku_id"], result)
            if result["observed_price_inr"] is not None:
                successes += 1
                print(f"  [{i}/{len(laptops)}] {l['sku_id']}: "
                      f"₹{result['observed_price_inr']:,} (MSRP on file: ₹{l['msrp_inr']:,.0f}) "
                      f"from {result['retailer_name']}")
            else:
                misses += 1
                print(f"  [{i}/{len(laptops)}] {l['sku_id']}: no price found")
            log_rows.append({**l, **result})
        except Exception as e:
            errors += 1
            print(f"  [{i}/{len(laptops)}] {l['sku_id']}: ERROR - {e}")
            log_rows.append({**l, "error": str(e)})
        if not args.dry_run:
            time.sleep(REQUEST_DELAY_SECONDS)

    print(f"\nDone. {successes} prices found, {misses} misses, {errors} errors.")

    log_path = BASE_DIR / "data" / "price_refresh_log.json"
    with open(log_path, "w") as f:
        json.dump(log_rows, f, indent=2, default=str)
    print(f"Full log written to {log_path}")


if __name__ == "__main__":
    main()