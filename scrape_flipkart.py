"""Polite Flipkart laptop scraper -> CSV + .xlsx.  Run on YOUR machine:
    python scrape_flipkart.py [--dry-run]                                # 1. find laptops (+ price, MRP)
    python scrape_flipkart.py --specs [LISTING_CSV] [--limit 100]        # 2. full specs + price

Why this works differently from scrape_amazon.py: Flipkart's robots.txt disallows /search? and every URL
containing "page=", so typing "laptop" into search and walking the result pages is off limits. What it
does allow - and lists in the sitemaps it publishes for crawlers - are laptop landing pages:
    /laptops/hp~brand/pr?sid=6bo,b5g                  brand, processor and type pages
    /laptops/~laptops-under-rs40000/pr?sid=6bo,b5g    tag pages
    /q/best-laptops-under-rs-40000                    topic pages
Stage 1 reads three of those sitemaps, keeps the ~170 laptop pages, and reads the first (the only allowed)
page of each: 24 laptops a page with title, price, MRP, rating and the spec bullets. The pages overlap, so
this finds a large slice of Flipkart's laptops, not the whole catalogue. Stage 2 (--specs) opens each
laptop's product page and keeps ONLY the specifications and the price in INR:
  * price_inr = offers.price of the page's schema.org Product block (only when priceCurrency is INR)
  * the full Specifications table (Processor Name, RAM, Screen Size, Weight ...), read from the data the
    page embeds for its own rendering (label_0 = name, label_1 = value)
Flipkart's CSS class names are scrambled and change every few months, so cards are found by structure
(<div data-id="COM...">, the /p/ link, <li> bullets, "₹" texts) and product data from those two blocks.

Politeness is the same as scrape_amazon.py, whose fetcher this reuses: robots.txt is checked for every URL
and every redirect, one request at a time, waits cycle 30/60/120 s, back off on 429/5xx/529, resumable
CSVs saved after every page, an honest User-Agent, no proxy rotation or fingerprint spoofing. Normal
Flipkart pages contain words like "captcha", so a block is recognised by its effect instead: 3 pages in a
row without a single laptop -> stop (the last one is kept in data/debug/).

Note: robots.txt compliance is not permission. Flipkart's Terms of Use forbid robots, spiders and
page-scraping of the platform, so keep runs small and the data for personal/academic use.
"""
import argparse, csv, gzip, json, re, sys
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests

from scrape_amazon import (DELAYS, HEADERS, MIN_LAPTOP_PRICE, NUMERIC, OUT_DIR, PoliteSession, Robots, Stop,
                           _clean, _key, _money, load_specs, save, save_debug, save_specs, summary, tidy)

BASE = "https://www.flipkart.com"
LAPTOPS = f"{BASE}/laptops/pr?sid=6bo,b5g"  # Flipkart's Laptops store; sid=6bo,b5g marks every laptop page
SITEMAPS = ("sitemap_v_view-browse.xml.gz", "sitemap_t_tag-browse.xml.gz", "sitemap_q_query-browse.xml.gz")
LAPTOP_WORDS = re.compile(r"\b(laptops?|macbooks?|chromebooks?|notebooks?)\b")
NOT_LAPTOP_PAGES = re.compile(r"\b(bags?|tables?|desks?|stands?|skins?|stickers?|speakers?|chargers?|adapters?|"
                              r"batter(y|ies)|backpacks?|trolley|sleeves?|covers?|cases?|keyboards?|mouse|"
                              r"cooling|power bank)\b")
COLUMNS = ["pid", "title", "brand", "price_inr", "mrp_inr", "rating", "rating_count", "highlights", "source", "url",
           "observed_date"]
# Rows of the Specifications table that describe the seller or the paperwork, not the laptop.
NOT_SPECS = {"name_and_address_of_the_packer", "name_and_address_of_the_manufacturer",
             "name_and_address_of_the_importer", "country_of_origin", "is_fragile", "sales_package", "generic_name",
             "net_quantity", "covered_in_warranty", "not_covered_in_warranty", "warranty_service_type"}


def too_cheap(row):
    """Every page read is in Flipkart's Laptops category, so the only filter needed is the price floor; the
    accessory-word check scrape_amazon.py uses would only add false alarms here."""
    return bool(row.get("price_inr")) and row["price_inr"] < MIN_LAPTOP_PRICE


def load_robots():
    return Robots(requests.get(f"{BASE}/robots.txt", headers=HEADERS, timeout=20).text)


# ---------------------------------------------------------------------------
# Finding the laptop pages (Flipkart's own sitemaps)
# ---------------------------------------------------------------------------

def laptop_page(url):
    if "/hi/" in url:  # the Hindi copy of a page we already have
        return False
    if "sid=6bo,b5g" in url:
        return True
    if "/q/" in url:
        words = url.rsplit("/q/", 1)[1].replace("-", " ")
        return bool(LAPTOP_WORDS.search(words)) and not NOT_LAPTOP_PAGES.search(words)
    return False


def discover(sess):
    """The laptops store page plus every laptop landing page in the sitemaps (the URLs Flipkart invites
    crawlers to fetch). Sitemaps are XML, so they're read with ElementTree rather than BeautifulSoup."""
    pages = [LAPTOPS]
    for name in SITEMAPS:
        r = sess.get(f"{BASE}/{name}")
        if r is None:
            continue
        data = gzip.decompress(r.content) if r.content[:2] == b"\x1f\x8b" else r.content
        locs = [el.text.strip() for el in ET.fromstring(data).iter("{http://www.sitemaps.org/schemas/sitemap/0.9}loc")]
        found = [u for u in locs if laptop_page(u) and sess.robots.allowed(u)]
        print(f"  {name}: {len(locs)} pages listed, {len(found)} laptop pages")
        pages += found
    return list(dict.fromkeys(pages))


def source_of(url):
    """'https://www.flipkart.com/laptops/hp~brand/pr?sid=6bo,b5g' -> 'laptops/hp~brand'."""
    return re.sub(r"/pr$", "", urlparse(url).path.strip("/"))


# ---------------------------------------------------------------------------
# Landing pages: one row per laptop card (find / find_all)
# ---------------------------------------------------------------------------

def _json_blocks(soup):
    """Every schema.org object in the page's <script type="application/ld+json"> tags."""
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except ValueError:
            continue
        yield from (b for b in (data if isinstance(data, list) else [data]) if isinstance(b, dict))


def parse_listing(soup, source):
    """A card is <div data-id="COMH..."> (the Flipkart product id). Its texts run: title, rating, 'N Ratings
    & M Reviews', the spec bullets (<li>), price, struck-through MRP, 'NN% off', then exchange/bank offers
    ('Upto ₹58,650 Off on Exchange') - those offer amounts must never be read as a price."""
    full = {}  # pid -> untruncated title, from the page's schema.org ItemList
    for block in _json_blocks(soup):
        for item in block.get("itemListElement", []):
            pid = re.search(r"[?&]pid=(\w+)", item.get("url", ""))
            if pid and item.get("name"):
                full[pid.group(1)] = item["name"]
    rows = []
    for card in soup.find_all("div", attrs={"data-id": True}):
        link = card.find("a", href=re.compile(r"/p/itm"))
        if link is None:
            continue
        pid = card["data-id"]
        # each element's own text, in page order; the struck MRP comes as separate pieces "₹" + "2,55,379"
        texts = [t for t in (_clean(" ".join(el.find_all(string=True, recursive=False)))
                             for el in card.find_all(True) if el.name not in ("script", "style")) if t]
        prices = []
        for t in texts:
            if "Upto" in t or "Exchange" in t or "Bank Offer" in t:
                break
            if t.startswith("₹"):
                prices.append(_money(t))
            if t.endswith("% off"):
                break
        rated = re.search(r"(?<![\d.,])([0-5](?:\.\d)?)\s+([\d,]+)\s+Ratings", " ".join(texts))
        rows.append(tidy({
            "pid": pid,
            "title": full.get(pid) or next((t for t in texts if len(t) >= 20 and not t.startswith("₹")), None),
            "brand": None,  # tidy() takes it from the title
            "price_inr": prices[0] if prices else None,
            "mrp_inr": prices[1] if len(prices) > 1 else None,
            "rating": float(rated.group(1)) if rated else None,
            "rating_count": int(rated.group(2).replace(",", "")) if rated else None,
            "highlights": " | ".join(li.get_text(" ", strip=True) for li in card.find_all("li")) or None,
            "source": source,
            "url": f"{urljoin(BASE, link['href'].split('?')[0])}?pid={pid}",
            "observed_date": str(date.today()),
        }))
    return rows


# ---------------------------------------------------------------------------
# Product pages: specifications + price in INR
# ---------------------------------------------------------------------------

def product_price(soup):
    """offers.price of the schema.org Product block - the selling price, not the MRP or a bank-offer price."""
    for block in _json_blocks(soup):
        if block.get("@type") != "Product":
            continue
        offers = block.get("offers") or {}
        for offer in offers if isinstance(offers, list) else [offers]:
            price = offer.get("price") or offer.get("lowPrice")
            if price and offer.get("priceCurrency") == "INR":  # not rupees -> never in a price_inr column
                return int(float(price))
    return None


def page_state(soup):
    """The JSON the page embeds for its own rendering: <script>window.__INITIAL_STATE__ = {...};</script>."""
    tag = soup.find("script", string=re.compile(r"window\.__INITIAL_STATE__\s*="))
    if tag is None:
        return None
    start = re.search(r"window\.__INITIAL_STATE__\s*=\s*", tag.string).end()
    try:
        return json.JSONDecoder().raw_decode(tag.string, start)[0]
    except ValueError:
        return None


def _label(node, name):
    """node["label_0"]["value"]["text"], or None."""
    part = node.get(name)
    value = part.get("value") if isinstance(part, dict) else None
    return value.get("text") if isinstance(value, dict) else None


def product_specs(state):
    """Specification rows look like {"label_0": {"value": {"text": "Processor Name"}},
    "label_1": {"value": {"text": ["Ryzen 3 Quad Core"]}}}. Only spec rows carry their value as a list;
    the offers, delivery dates and carousels on the same page use plain strings."""
    specs, stack = {}, [state]
    while stack:  # depth-first, in page order
        node = stack.pop()
        if isinstance(node, dict):
            name, value = _label(node, "label_0"), _label(node, "label_1")
            if isinstance(name, str) and isinstance(value, list):
                key, text = _key(name), _clean(", ".join(str(v) for v in value if v))
                # 'Operating System' is listed twice ('Windows 11', 'Windows 11 Home'): keep the fuller one
                if key and text and key not in NOT_SPECS and len(text) > len(specs.get(key, "")):
                    specs[key] = text
            stack.extend(reversed(list(node.values())))
        elif isinstance(node, list):
            stack.extend(reversed(node))
    return specs


def parse_product(soup):
    """-> (specs, price_inr)."""
    state = page_state(soup)
    return (product_specs(state) if state else {}), product_price(soup)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def specs_path(listing_csv):
    return listing_csv.with_name(listing_csv.stem + "_specs.csv")


def latest_listing():
    found = sorted(p for p in OUT_DIR.glob("flipkart_laptops_*.csv")
                   if re.fullmatch(r"flipkart_laptops_\d{4}-\d{2}-\d{2}\.csv", p.name))
    return found[-1] if found else None


def load_listing(out):
    """Resume support: rows already in the CSV, plus {"pages": [...], "done": [...]}."""
    rows, progress, prog_path = {}, {}, out.with_suffix(".progress.json")
    if out.exists():
        with open(out, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                r = {k: (v if v != "" else None) for k, v in r.items()}
                for k in NUMERIC:
                    r[k] = float(r[k]) if r.get(k) else None
                rows[r["pid"]] = r
    if prog_path.exists():
        progress = json.loads(prog_path.read_text(encoding="utf-8"))
    return rows, progress, prog_path


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def dry_run(robots):
    print(f"crawl-delay: {robots.crawl_delay or 'none'}; what robots.txt says about the URLs this script uses:")
    for u in [LAPTOPS, f"{BASE}/{SITEMAPS[0]}", f"{BASE}/laptops/hp~brand/pr?sid=6bo,b5g",
              f"{BASE}/q/best-laptops-under-rs-40000",
              f"{BASE}/hp-255-g10-thin-light-laptop/p/itm894f74dac8f0c?pid=COMHEGJWZG8F5FGP",
              f"{BASE}/laptops/pr?sid=6bo,b5g&page=2", f"{BASE}/search?q=laptop"]:
        print(" ", "ok      " if robots.allowed(u) else "BLOCKED ", u)
    print("(the last two are why this scraper reads landing pages instead of searching and paging)")


def main(out, dry, delays=DELAYS, empty_limit=3):
    """Stage 1: laptop landing pages -> listing CSV."""
    robots = load_robots()
    if dry:
        return dry_run(robots)
    rows, progress, prog_path = load_listing(out)
    sess = PoliteSession(robots, robots.crawl_delay, delays, markers=())

    def write_progress():
        prog_path.write_text(json.dumps(progress, indent=1), encoding="utf-8")

    try:
        if not progress.get("pages"):
            print("reading Flipkart's sitemaps for laptop pages ...")
            progress = {"pages": discover(sess), "done": []}
            write_progress()
        pages, done = progress["pages"], set(progress["done"])
        print(f"{len(pages)} laptop pages, {len(done)} done already, {len(rows)} laptops so far "
              f"(~{(len(pages) - len(done)) * sum(delays) / len(delays) / 3600:.1f} h at {delays} s waits)")
        empty = 0
        for i, url in enumerate(pages, 1):
            if url in done:
                continue
            soup = sess.soup(url)
            if soup is None:  # robots.txt said no (or the page redirected to a URL it disallows)
                progress["done"].append(url); write_progress(); continue
            found = parse_listing(soup, source_of(url))
            laptops = [r for r in found if not too_cheap(r)]
            new = list({r["pid"]: r for r in laptops if r["pid"] not in rows}.values())  # sponsored repeats
            rows.update((r["pid"], r) for r in new)
            print(f"  {i}/{len(pages)} {source_of(url)}: {len(found)} laptops, {len(new)} new (total {len(rows)})")
            if not found:
                # Not marked done, so a rerun retries it. Several in a row = Flipkart is turning us away.
                empty += 1
                if empty >= empty_limit:
                    saved = save_debug(str(soup), "flipkart_empty")
                    raise Stop(f"{empty} pages in a row without a single laptop - Flipkart may be turning us "
                               f"away. Try again in a few hours. Last page: {saved}")
                continue
            empty = 0
            progress["done"].append(url); write_progress()
            save(list(rows.values()), out, quiet=True, columns=COLUMNS)  # checkpoint after every page
    except Stop as e:
        print("STOPPED:", e)
    except KeyboardInterrupt:
        print("interrupted - saving what we have")
    finally:
        if rows:
            summary(list(rows.values()), "pid")
            save(list(rows.values()), out, columns=COLUMNS)


def specs_main(listing, limit, dry, delays=DELAYS, empty_limit=5):
    """Stage 2: product page of every laptop in the listing CSV -> <listing>_specs.csv (specs + price only)."""
    out = specs_path(listing)
    listed = load_listing(listing)[0]
    done = load_specs(out, "pid")
    todo = [r for pid, r in listed.items() if pid not in done][:limit]
    hours = len(todo) * sum(delays) / len(delays) / 3600
    print(f"{len(listed)} laptops in {listing.name}; {len(done)} already in {out.name}; "
          f"{len(todo)} to fetch this run (~{hours:.1f} h at {delays} s waits)")
    robots = load_robots()
    if dry:
        for r in todo[:3]:
            print(" ", "ok      " if robots.allowed(r["url"]) else "BLOCKED ", r["url"])
        return

    sess, empty = PoliteSession(robots, robots.crawl_delay, delays, markers=()), 0
    try:
        for i, row in enumerate(todo, 1):
            soup = sess.soup(row["url"])
            specs, price = parse_product(soup) if soup is not None else ({}, None)
            if not specs and price is None:
                # Not saved, so a rerun retries it. Many in a row means the page layout changed or Flipkart
                # is serving stripped pages - better to stop than to spend hours collecting blanks.
                empty += 1
                print(f"  {i}/{len(todo)} {row['pid']}: no specs or price found ({empty} in a row)")
                if empty >= empty_limit:
                    saved = save_debug(str(soup), "flipkart_product") if soup is not None else None
                    raise Stop(f"{empty} product pages in a row had no specs or price - stopping to check"
                               + (f" (last page: {saved})" if saved else ""))
                continue
            empty = 0
            done[row["pid"]] = {"pid": row["pid"], **specs, "price_inr": price, "url": row["url"],
                                "observed_date": str(date.today())}
            save_specs(list(done.values()), out, quiet=True, id_col="pid")  # checkpoint after every product
            print(f"  {i}/{len(todo)} {row['pid']}: {len(specs)} specs, " + (f"₹{price:,}" if price else "no price")
                  + f" | {specs.get('brand', '')} {specs.get('model_name', '')}".rstrip())
    except Stop as e:
        print("STOPPED:", e)
    except KeyboardInterrupt:
        print("interrupted - saving what we have")
    finally:
        if done:
            print(f"{len(done)} laptops, {sum(1 for r in done.values() if r.get('price_inr'))} with a price in INR")
            save_specs(list(done.values()), out, id_col="pid")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles can't print ₹ otherwise
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--specs", nargs="?", const="latest", type=str, default=None, metavar="LISTING_CSV",
                    help="stage 2: open every laptop's product page for specs + price (default: newest listing CSV)")
    ap.add_argument("--limit", type=int, default=None, help="--specs: at most N product pages this run")
    ap.add_argument("--delays", type=float, nargs="+", default=DELAYS,
                    help="seconds between requests, cycled (default: 30 60 120)")
    ap.add_argument("--out", type=Path, default=OUT_DIR / f"flipkart_laptops_{date.today()}.csv")
    ap.add_argument("--dry-run", action="store_true", help="only check robots.txt")
    a = ap.parse_args()
    delays = tuple(a.delays)
    if a.specs:
        listing = latest_listing() if a.specs == "latest" else Path(a.specs)
        if listing is None or not listing.exists():
            sys.exit(f"no listing CSV found ({a.specs}); run stage 1 first or pass its path")
        specs_main(listing, a.limit, a.dry_run, delays)
    else:
        main(a.out, a.dry_run, delays)
    sys.exit(0)
