"""Polite Amazon.in laptop scraper -> CSV.  Run on YOUR machine:
    python scrape_amazon.py [--pages N] [--queries "gaming laptop" "hp laptop"] [--dry-run]   # 1. find laptops
    python scrape_amazon.py --specs [LISTING_CSV] [--limit 100] [--dry-run]                   # 2. specs + price
    python scrape_amazon.py --from-html saved_pages/     # parse pages you saved from your browser (Ctrl+S)
    python scrape_amazon.py --tidy [CSV]                 # re-clean an older CSV + write its .xlsx; no network

Stage 1 walks search-result pages for each query (Laptops category only) and writes the listing CSV:
one row per ASIN with title, brand, price, MRP, rating. Accessories that leak into the Laptops results
(screen protectors, skins, chargers, webcams ...) are dropped: anything under ₹5,000, or with an accessory
word in the first 8 words of its title. Stage 2 (--specs) opens each ASIN's product page and
writes <listing>_specs.csv with ONLY the model's specifications and its price in INR:
  * the "Product overview" table: <tr class="po-..."> rows, label in td.a-span3, value in td.a-span9
  * the "Technical details" tables (model number, weight, battery, ports ...) for whatever the overview lacks
  * price = span.a-price-whole inside the buy-box price block (never the struck-through MRP)
Stage 2 parses with BeautifulSoup's find / find_all. --specs without a path uses the newest listing CSV.

Amazon.in may answer scripted requests with an Akamai bot challenge even on robots-allowed URLs.
The live mode detects that and stops (it never solves or spoofs the challenge); --from-html is the
fallback: browse normally, save search/product pages as "Webpage, HTML only", and parse them offline.

Politeness rules, all enforced in code:
  * every URL is checked against amazon.in/robots.txt before it is fetched (wildcard-aware matcher,
    because urllib.robotparser ignores '*' and '$'); a disallowed URL is skipped, never fetched
  * one request at a time; waits cycle 30/60/120 s (--delays; or the robots Crawl-delay, if larger)
  * each query is followed page by page until the pagination strip's Next button is disabled, or until
    2 pages in a row add no new laptop (--stale-pages; later pages of overlapping queries are mostly repeats)
  * the CSV is rewritten after every page / product, so a long run that stops early keeps everything so far
  * 429/5xx or a dropped connection -> back off 30/60/120 s, then give up
  * a bot challenge (CAPTCHA / Akamai) -> go quiet 5 min, then 15 min; a third one stops the run. The
    challenge is never solved or faked, and the page is kept in data/debug/ for inspection
  * resumable: rerunning keeps the rows already in the CSV and continues where it stopped (search progress
    is tracked in <csv>.progress.json; --specs skips ASINs already in the specs CSV)
  * an honest User-Agent; no proxy rotation, no fingerprint spoofing
Blank = unknown (never 0), same rule as the catalogue.

Every finished run also writes an .xlsx copy next to each CSV - open that one in Excel. In the CSV a
blank value is just two commas in a row, and an import that "treats consecutive delimiters as one"
(Text Import Wizard / Text to Columns) squeezes those out and slides the rest of the row left, which
puts prices under 'brand' and ratings under 'mrp_inr'. In the .xlsx every value already has its cell.

Note: robots.txt compliance is not permission. Amazon's Conditions of Use restrict automated data
collection, so keep runs small and the data for personal/academic use; observed prices still go
through import_prices.py, which needs a URL and a date for every number.
"""
import argparse, csv, itertools, json, re, shutil, sys, time, unicodedata, zipfile
from datetime import date
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse
from xml.sax.saxutils import escape

import requests
from bs4 import BeautifulSoup

BASE = "https://www.amazon.in"
LAPTOPS_NODE = "1375424031"  # amazon.in browse node for Laptops; keeps bags/accessories out of results
UA = "Mozilla/5.0 (compatible; SpecSenseBot/0.1; academic laptop-price research)"
HEADERS = {"User-Agent": UA, "Accept-Language": "en-IN,en;q=0.9"}
DELAYS = (30, 60, 120)  # seconds between requests, cycled 30 -> 60 -> 120 -> 30 ...
BACKOFF = (30, 60, 120)
CHALLENGE_MARKERS = ("validateCaptcha", "Type the characters you see", "bm-verify", "/_sec/verify")
CHALLENGE_COOLDOWN = (300, 900)  # a bot challenge -> go quiet 5 min, then 15 min, then stop (never solved)
OUT_DIR = Path(__file__).resolve().parent / "data"  # Spec-Sense-RAG-Project/data/
DEFAULT_QUERIES = ["laptop", "gaming laptop", "thin and light laptop", "2 in 1 laptop", "chromebook",
                   "hp laptop", "dell laptop", "lenovo laptop", "asus laptop", "acer laptop", "msi laptop",
                   "apple macbook", "samsung galaxy book", "microsoft surface laptop"]
COLUMNS = ["asin", "title", "brand", "price_inr", "mrp_inr", "rating", "rating_count", "sponsored", "query",
           "url", "observed_date"]
# Rows of the technical-details tables that describe the listing or the seller, not the laptop.
NOT_SPECS = {"asin", "customer_reviews", "best_sellers_rank", "date_first_available", "manufacturer",
             "packer", "importer", "net_quantity", "generic_name", "country_of_origin", "unit_count",
             "number_of_items", "item_type_name", "importer_contact_information",
             "manufacturer_contact_information", "packer_contact_information"}
# Brand from the title, for search layouts that don't show one: brand names, then series names.
BRANDS = {b.lower(): b for b in (
    "HP", "Dell", "Lenovo", "ASUS", "Acer", "MSI", "Apple", "Samsung", "Microsoft", "Alienware", "Razer", "Gigabyte",
    "Infinix", "Chuwi", "Avita", "Primebook", "Honor", "Huawei", "Xiaomi", "Redmi", "Realme", "LG", "Zebronics",
    "Futopia", "Fujitsu", "Dynabook", "Toshiba", "Vaio", "Google", "Alketron", "Bmax", "Lexibook")}
SERIES = {"ideapad": "Lenovo", "thinkpad": "Lenovo", "thinkbook": "Lenovo", "yoga": "Lenovo", "legion": "Lenovo",
          "loq": "Lenovo", "vivobook": "ASUS", "zenbook": "ASUS", "expertbook": "ASUS", "rog": "ASUS", "tuf": "ASUS",
          "pavilion": "HP", "victus": "HP", "omen": "HP", "envy": "HP", "spectre": "HP", "probook": "HP",
          "elitebook": "HP", "omnibook": "HP", "inspiron": "Dell", "latitude": "Dell", "vostro": "Dell", "xps": "Dell",
          "aspire": "Acer", "nitro": "Acer", "predator": "Acer", "swift": "Acer", "travelmate": "Acer",
          "macbook": "Apple", "surface": "Microsoft", "galaxy": "Samsung", "jiobook": "Jio"}
# Accessory words that never appear in the first 8 words of a real laptop title ("Saco Anti Glare Scratch
# Ultra-Clear Screen Protector for ...", "Keyboard Cover for Lenovo ..."). Checked against all 2,417 rows of
# the 2026-10-20 listing: every hit was an accessory.
ACCESSORY = re.compile(r"\b(screen ?protector|screen ?guard|protector|decals?|stickers?|skins?|lamination|"
                       r"(?<!backlit )keyboard|"  # "Acer Aspire Lite Metal, Backlit Keyboard ..." is a laptop
                       r"cover|case|sleeve|bag|backpack|adapter|charger|battery|webcam|mouse|stand|hub|dock|docking|"
                       r"cooling|cooler|fan|replacement|steering|lock|cable|jack|hinge|power ?bank)\b")
MIN_LAPTOP_PRICE = 5000  # cheapest real laptop in the listing is ₹11,635; below ₹5,000 it's skins and protectors


class Stop(Exception):
    """Raised when the site asks us to stop (CAPTCHA, repeated throttling)."""


# ---------------------------------------------------------------------------
# robots.txt
# ---------------------------------------------------------------------------

class Robots:
    """Google-spec robots.txt matching: '*' wildcard, '$' end anchor, longest rule wins, Allow wins ties."""

    def __init__(self, text, agent="SpecSenseBot"):
        groups, agents, rules, last_was_rule = [], [], [], False
        for line in text.splitlines():
            line = line.split("#", 1)[0].strip()
            if ":" not in line:
                continue
            key, val = (p.strip() for p in line.split(":", 1))
            key = key.lower()
            if key == "user-agent":
                if last_was_rule:
                    groups.append((agents, rules)); agents, rules = [], []
                agents.append(val.lower()); last_was_rule = False
            elif key in ("allow", "disallow", "crawl-delay"):
                rules.append((key, val)); last_was_rule = True
        groups.append((agents, rules))
        mine = [r for a, r in groups if any(x != "*" and x in agent.lower() for x in a)]
        chosen = mine or [r for a, r in groups if "*" in a]
        self.rules = [(k, v) for r in chosen for k, v in r if k != "crawl-delay" and v]
        delays = [float(v) for r in chosen for k, v in r if k == "crawl-delay" and v.replace(".", "", 1).isdigit()]
        self.crawl_delay = max(delays, default=0.0)

    @staticmethod
    def _regex(pattern):
        anchored = pattern.endswith("$")
        body = re.escape(pattern.rstrip("$")).replace(r"\*", ".*")
        return re.compile(body + ("$" if anchored else ""))

    def allowed(self, url):
        p = urlparse(url)
        path = (p.path or "/") + (f"?{p.query}" if p.query else "")
        best = None  # (pattern length, is_allow)
        for kind, pat in self.rules:
            if self._regex(pat).match(path):
                cand = (len(pat), kind == "allow")
                best = cand if best is None or cand > best else best
        return best is None or best[1]


def load_robots():
    return Robots(requests.get(f"{BASE}/robots.txt", headers=HEADERS, timeout=20).text)


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

class PoliteSession:
    def __init__(self, robots, min_delay, delays=DELAYS, markers=CHALLENGE_MARKERS):
        self.s = requests.Session(); self.s.headers.update(HEADERS)
        self.robots, self.min_delay, self.last = robots, min_delay, None
        self.delays = itertools.cycle(delays)
        self.markers = markers  # text that only a bot-challenge page contains (site-specific)

    def soup(self, url):
        """Returns parsed HTML, or None if robots.txt disallows the URL. Raises Stop when told to stop."""
        r = self.get(url)
        return BeautifulSoup(r.text, "html.parser") if r is not None else None

    def get(self, url, hops=5):
        """The polite fetch: robots check, wait, backoff, challenge cool-down. -> Response, or None if
        robots.txt disallows the URL (or a redirect to one). Redirects are followed by hand, so a redirect
        to a disallowed URL (say /search?...) is never fetched."""
        if not self.robots.allowed(url):
            print("  robots.txt disallows, skipped:", url)
            return None
        errors = challenges = 0
        while True:
            if self.last is not None:  # no wait before the very first request
                wait = max(self.min_delay, next(self.delays)) - (time.time() - self.last)
                if wait > 0:
                    print(f"  waiting {wait:.0f} s")
                    time.sleep(wait)
            try:
                r = self.s.get(url, timeout=25, allow_redirects=False)
            except (requests.ConnectionError, requests.Timeout) as e:  # e.g. WinError 10054, connection reset
                self.last = time.time()
                if errors < len(BACKOFF):
                    print(f"  network error ({type(e).__name__}), backing off {BACKOFF[errors]} s")
                    time.sleep(BACKOFF[errors]); errors += 1; continue
                raise Stop(f"network keeps failing on {url} ({e}) - stopping; rerun later to resume")
            self.last = time.time()
            if r.is_redirect and hops:
                return self.get(urljoin(url, r.headers["Location"]), hops - 1)
            if r.status_code == 200:
                if "html" not in r.headers.get("content-type", "text/html"):
                    return r  # a sitemap (.xml.gz) or other file - nothing to decode or check
                r.encoding = r.apparent_encoding or "utf-8"
                hits = [m for m in self.markers if m in r.text]
                if not hits:
                    return r
                saved = save_debug(r.text, "challenge")
                if challenges < len(CHALLENGE_COOLDOWN):
                    # Amazon's bot protection flags bursts of requests; going quiet for a while usually clears it.
                    # We only wait and ask again later - the challenge itself is never solved or faked.
                    print(f"  bot challenge ({', '.join(hits)}; page saved to {saved.name}) - cooling down "
                          f"{CHALLENGE_COOLDOWN[challenges] // 60} min")
                    time.sleep(CHALLENGE_COOLDOWN[challenges]); challenges += 1; continue
                raise Stop(f"Amazon kept serving a bot challenge ({', '.join(hits)}) after cooling down - it wants "
                           f"us to stop. Try again in a few hours, or use --from-html. Last page: {saved}")
            if r.status_code == 404:
                return None
            if r.status_code in (429, 500, 502, 503, 529) and errors < len(BACKOFF):  # 529 = Flipkart "overloaded"
                print(f"  HTTP {r.status_code}, backing off {BACKOFF[errors]} s")
                time.sleep(BACKOFF[errors]); errors += 1; continue
            raise Stop(f"HTTP {r.status_code} on {url} - stopping")


def save_debug(html, kind):
    """Keeps the page that triggered a stop, so we can see what Amazon actually sent."""
    path = OUT_DIR / "debug" / f"{kind}_{time.strftime('%Y%m%d-%H%M%S')}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Search pages
# ---------------------------------------------------------------------------

def _money(text):
    digits = re.sub(r"[^\d.]", "", text or "")
    try:
        return float(digits) if digits else None
    except ValueError:
        return None


def _text(el, sel):
    found = el.select_one(sel)
    return found.get_text(" ", strip=True) if found else None


def _plain(title):
    """Sellers write titles in 'mathematical bold' letters to stand out (𝗗𝗲𝗹𝗹𝗠𝗼𝗱𝗲𝗹 5420). Maps them back to
    plain letters, with a space where a bold run was glued to the next word, and drops direction marks."""
    if not title:
        return title
    bold = lambda m: unicodedata.normalize("NFKC", m.group(1)) + (" " if m.group(2) else "")
    return _clean(re.sub(r"([\U0001D400-\U0001D7FF]+)(?=(\w)?)", bold, title))


def brand_from_title(title):
    words = re.findall(r"[a-z0-9]+", (title or "").lower())[:8]
    for w in words:
        if w in BRANDS or w in SERIES:
            return BRANDS.get(w) or SERIES[w]
    for i, w in enumerate(words):  # glued words: "DellModel 5420", "HPProbook 640"
        for b, name in BRANDS.items():
            if w.startswith(b) and (i == 0 or len(b) >= 4):
                return name
    return None


def not_a_laptop(row):
    """-> why the row is an accessory rather than a laptop, or None."""
    if row.get("price_inr") and row["price_inr"] < MIN_LAPTOP_PRICE:
        return f"₹{row['price_inr']:,.0f}"
    hit = ACCESSORY.search(" ".join(re.findall(r"[a-z0-9]+", (row.get("title") or "").lower())[:8]))
    return f"'{hit.group()}' in the title" if hit else None


def tidy(row):
    """Cleans one listing row; used on fresh search results and, via --tidy, on CSVs from older versions."""
    row["title"] = _plain(row.get("title"))
    row["brand"] = row.get("brand") or brand_from_title(row["title"])
    if row.get("mrp_inr") and row.get("price_inr") and row["mrp_inr"] < row["price_inr"]:
        row["mrp_inr"] = None  # an "MRP" below the selling price is a per-unit price ("₹131.67/count")
    return row


def parse_search(soup, query):
    rows = []
    for card in soup.select('div[data-component-type="s-search-result"][data-asin]'):
        asin = card.get("data-asin")
        if not asin:
            continue
        rating = re.search(r"([\d.]+) out of 5", _text(card, "span.a-icon-alt") or "")
        count = _text(card, 'a[href*="customerReviews"] span') or _text(card, "span.s-underline-text")
        # Brand-search layouts have two <h2>s: a short brand line, then the product title. Longest = title.
        heads = sorted({h.get("aria-label") or h.get_text(" ", strip=True) for h in card.select("h2")} - {""}, key=len)
        rows.append(tidy({
            "asin": asin,
            "title": heads[-1] if heads else None,
            "brand": heads[0] if len(heads) > 1 else None,
            "price_inr": _money(_text(card, "span.a-price:not(.a-text-price) span.a-offscreen")),
            # the MRP is the struck-through price; a plain a-text-price can be the per-unit price instead
            "mrp_inr": _money(_text(card, 'span.a-price.a-text-price[data-a-strike="true"] span.a-offscreen')
                              or _text(card, "span.a-price.a-text-price span.a-offscreen")),
            "rating": float(rating.group(1)) if rating else None,
            "rating_count": int(re.sub(r"\D", "", count)) if count and re.sub(r"\D", "", count) else None,
            "sponsored": "Sponsored" in card.get_text(" ", strip=True)[:300],
            "query": query,
            "url": f"{BASE}/dp/{asin}",
            "observed_date": str(date.today()),
        }))
    return rows, pagination(soup)


def pagination(soup):
    """Reads the pagination strip: (has_next, last_page). Enabled Next is an <a>; on the last page it
    becomes a disabled <span>. No strip at all (single page, or a stripped-down page) -> stop."""
    strip = soup.select_one(".s-pagination-strip, .s-pagination-container")
    if strip is None:
        return False, None
    nxt = strip.select_one(".s-pagination-next")
    has_next = nxt is not None and nxt.name == "a" and "s-pagination-disabled" not in nxt.get("class", [])
    pages = [int(t) for t in (e.get_text(strip=True) for e in strip.select(".s-pagination-item")) if t.isdigit()]
    return has_next, max(pages, default=None)


# ---------------------------------------------------------------------------
# Product pages: specifications + price in INR (find / find_all only)
# ---------------------------------------------------------------------------

def _clean(s):
    """Drops the invisible left-to-right marks Amazon puts around values, and squeezes whitespace."""
    return re.sub(r"\s+", " ", (s or "").replace("‎", "").replace("‏", "")).strip(" :")


def _key(label):
    """'Ram Memory Installed Size' -> 'ram_memory_installed_size'."""
    return re.sub(r"[^a-z0-9]+", "_", _clean(label).lower()).strip("_")


def _value(td):
    """Long values come as a hidden full copy plus a visible cut-off copy ('...'); keep only the full one."""
    full = td.find("span", class_="a-truncate-full")
    return _clean((full or td).get_text(" ", strip=True))


def product_overview(soup):
    """The 'Product overview' table: <tr class="a-spacing-small po-brand"> rows, label in td.a-span3,
    value in td.a-span9 (see the markup in the screenshots)."""
    specs = {}
    box = soup.find("div", id="productOverview_feature_div")
    if box is None:
        return specs
    for tr in box.find_all("tr", class_=lambda c: c is not None and c.startswith("po-")):
        label, value = tr.find("td", class_="a-span3"), tr.find("td", class_="a-span9")
        if label and value and _value(value):
            specs[_key(label.get_text())] = _value(value)
    return specs


def technical_details(soup):
    """'Technical details' / 'Additional information' tables (th = label, td = value), and the bullet-list
    layout some listings use instead (<span class="a-text-bold">Label</span><span>value</span>)."""
    specs = {}
    for table in soup.find_all("table", class_="prodDetTable"):
        for tr in table.find_all("tr"):
            th, td = tr.find("th"), tr.find("td")
            if th and td:
                specs.setdefault(_key(th.get_text()), _value(td))
    bullets = soup.find("div", id="detailBullets_feature_div")
    if bullets:
        for li in bullets.find_all("li"):
            bold = li.find("span", class_="a-text-bold")
            val = bold.find_next_sibling("span") if bold else None
            if val:
                specs.setdefault(_key(bold.get_text()), _clean(val.get_text(" ", strip=True)))
    return {k: v for k, v in specs.items() if k and v and k not in NOT_SPECS}


def product_price(soup):
    """Selling price in INR from the buy box: span.a-price-whole ("213,126") inside the price-to-pay block.
    Searched only inside the buy-box price containers, so the struck-through MRP and the prices of
    'similar items' carousels can never be picked up."""
    for box_id in ("corePriceDisplay_desktop_feature_div", "corePrice_desktop", "corePrice_feature_div",
                   "apex_desktop"):
        box = soup.find("div", id=box_id)
        if box is None:
            continue
        pay = box.find("span", class_=["priceToPay", "apexPriceToPay"]) or box.find(
            lambda t: t.name == "span" and "a-price" in t.get("class", []) and "a-text-price" not in t.get("class", []))
        if pay is None:
            continue
        symbol = pay.find("span", class_="a-price-symbol")
        if symbol and _clean(symbol.get_text()) not in ("₹", "INR", "Rs", "Rs."):
            return None  # not rupees - never store it in a price_inr column
        whole = pay.find("span", class_="a-price-whole")
        # a-price-whole holds "213,126" followed by a child <span class="a-price-decimal">; take the first text only
        text = whole.find(string=True) if whole else (pay.find("span", class_="a-offscreen") or pay).get_text()
        price = _money(text)
        if price:
            return int(price)
    return None


def parse_product(soup):
    """-> (specs, price_inr). Overview values win; technical details only fill in what the overview lacks."""
    specs = product_overview(soup)
    for k, v in technical_details(soup).items():
        specs.setdefault(k, v)
    return specs, product_price(soup)


# ---------------------------------------------------------------------------
# CSV helpers
# ---------------------------------------------------------------------------

def search_url(query, page):
    return f"{BASE}/s?k={quote_plus(query)}&rh=n%3A{LAPTOPS_NODE}&page={page}"


def specs_path(listing_csv):
    return listing_csv.with_name(listing_csv.stem + "_specs.csv")


def latest_listing():
    found = sorted(p for p in OUT_DIR.glob("amazon_laptops_*.csv")
                   if re.fullmatch(r"amazon_laptops_\d{4}-\d{2}-\d{2}\.csv", p.name))
    return found[-1] if found else None


def _write_csv(path, rows, columns):
    """Windows locks a file while Excel has it open. Rather than crash a long run, write <name>.unsaved.csv
    and say so; the next save goes to the real file again (and removes the spare) once it is closed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    spare = path.with_name(path.stem + ".unsaved" + path.suffix)
    for target in (path, spare):
        try:
            with open(target, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
                w.writeheader(); w.writerows(rows)
        except PermissionError:
            if target == spare:
                raise
            print(f"  ! {path.name} is open in another program (Excel locks it) - saving to {spare.name} "
                  f"instead; close it and the next save goes to the right file")
            continue
        if target == path:
            spare.unlink(missing_ok=True)
        return target


def _col(i):
    """0 -> A, 25 -> Z, 26 -> AA."""
    name = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        name = chr(65 + r) + name
    return name


_NOT_XML = re.compile("[^\t\n\r\x20-퟿-�\U00010000-\U0010ffff]")


def save_xlsx(rows, columns, path, sheet):
    """Excel copy of a CSV, built from plain zip + XML (no extra package): every value goes straight into
    its own cell, so nothing can slide into the wrong column. Numbers stay numbers; header frozen + filter."""
    def cell(ref, v):
        if v is None or v == "":
            return ""
        if isinstance(v, bool):
            return f'<c r="{ref}" t="b"><v>{int(v)}</v></c>'
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        text = escape(_NOT_XML.sub("", str(v))[:32767])  # 32,767 = Excel's limit per cell
        return f'<c r="{ref}" t="inlineStr"><is><t xml:space="preserve">{text}</t></is></c>'

    def number(k, v):  # specs CSVs come back as strings; keep the price columns numeric in Excel
        if k in NUMERIC and isinstance(v, str) and v:
            try:
                return float(v)
            except ValueError:
                return v
        return v

    cols = [_col(i) for i in range(len(columns))]
    lines = ['<row r="1">' + "".join(cell(f"{c}1", k) for c, k in zip(cols, columns)) + "</row>"]
    for n, r in enumerate(rows, 2):
        lines.append(f'<row r="{n}">' + "".join(cell(f"{c}{n}", number(k, r.get(k))) for c, k in zip(cols, columns))
                     + "</row>")
    widths = "".join(
        f'<col min="{i}" max="{i}" width="{min(60, max([len(k)] + [len(str(r.get(k) or "")) for r in rows[:300]]) + 2)}"'
        f' customWidth="1"/>' for i, k in enumerate(columns, 1))
    area = f"A1:{cols[-1]}{len(rows) + 1}"
    absolute = f"'{sheet}'!$A$1:${cols[-1]}${len(rows) + 1}"  # Excel's own name for the filter range
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    pkg = "http://schemas.openxmlformats.org/package/2006"
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    parts = {
        "[Content_Types].xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="{pkg}/content-types">'
            f'<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            f'<Default Extension="xml" ContentType="application/xml"/>'
            f'<Override PartName="/xl/workbook.xml" ContentType="{ct}.sheet.main+xml"/>'
            f'<Override PartName="/xl/worksheets/sheet1.xml" ContentType="{ct}.worksheet+xml"/></Types>',
        "_rels/.rels":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{pkg}/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/officeDocument" Target="xl/workbook.xml"/></Relationships>',
        "xl/_rels/workbook.xml.rels":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{pkg}/relationships">'
            f'<Relationship Id="rId1" Type="{rel}/worksheet" Target="worksheets/sheet1.xml"/></Relationships>',
        "xl/workbook.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook {ns} xmlns:r="{rel}">'
            f'<sheets><sheet name="{sheet}" sheetId="1" r:id="rId1"/></sheets><definedNames>'
            f'<definedName name="_xlnm._FilterDatabase" localSheetId="0" hidden="1">'
            f"{absolute}</definedName></definedNames></workbook>",
        "xl/worksheets/sheet1.xml":
            f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet {ns}>'
            f'<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft"'
            f' state="frozen"/></sheetView></sheetViews><cols>{widths}</cols>'
            f'<sheetData>{"".join(lines)}</sheetData><autoFilter ref="{area}"/></worksheet>',
    }
    try:
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for name, xml in parts.items():
                z.writestr(name, xml)
    except PermissionError:
        print(f"  ! {path.name} is open in Excel - not updated; close it and run: python scrape_amazon.py --tidy")
        return None
    return path


def save(rows, path, quiet=False, columns=COLUMNS):
    """quiet = the checkpoint after every page: CSV only. The final save also writes the .xlsx copy."""
    written = _write_csv(path, rows, columns)
    if not quiet:
        xlsx = save_xlsx(rows, columns, path.with_suffix(".xlsx"), "laptops")
        print(f"wrote {len(rows)} rows -> {written}" + (f" (+ {xlsx.name} for Excel)" if xlsx else ""))


def save_specs(rows, path, quiet=False, id_col="asin"):
    """Columns: asin, every spec seen (in first-seen order, so overview fields come first), price_inr, url, date."""
    tail = ["price_inr", "url", "observed_date"]
    specs = list(dict.fromkeys(k for r in rows for k in r if k not in tail and k != id_col))
    columns = [id_col] + specs + tail
    written = _write_csv(path, rows, columns)
    if not quiet:
        xlsx = save_xlsx(rows, columns, path.with_suffix(".xlsx"), "specs")
        print(f"wrote {len(rows)} rows, {len(specs)} spec columns -> {written}"
              + (f" (+ {xlsx.name} for Excel)" if xlsx else ""))


NUMERIC = ("price_inr", "mrp_inr", "rating", "rating_count")


def load_previous(out):
    """Resume support: rows already in the CSV, plus {query: {"page": last page done, "done": bool}}."""
    rows, progress, prog_path = {}, {}, out.with_suffix(".progress.json")
    if out.exists():
        with open(out, encoding="utf-8-sig", newline="") as f:
            for r in csv.DictReader(f):
                r = {k: (v if v != "" else None) for k, v in r.items()}
                for k in NUMERIC:
                    r[k] = float(r[k]) if r.get(k) else None
                r["sponsored"] = r.get("sponsored") == "True"
                rows[r["asin"]] = r
    if prog_path.exists():
        progress = json.loads(prog_path.read_text(encoding="utf-8"))
    return rows, progress, prog_path


def load_specs(path, id_col="asin"):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r[id_col]: {k: v for k, v in r.items() if v} for r in csv.DictReader(f)}


def summary(rows, id_col="asin"):
    priced = [r["price_inr"] for r in rows if r.get("price_inr")]
    print(f"{len(rows)} unique laptops, {len(priced)} with a price"
          + (f" (₹{min(priced):,.0f} - ₹{max(priced):,.0f})" if priced else ""))
    odd = [r[id_col] for r in rows if r.get("price_inr") and not 15000 <= r["price_inr"] <= 600000]
    if odd:
        print(f"{len(odd)} prices outside ₹15,000-6,00,000 (probably not a laptop): {', '.join(odd[:10])}")


def specs_summary(rows):
    rows = list(rows)
    print(f"{len(rows)} laptops, {sum(1 for r in rows if r.get('price_inr'))} with a price in INR")
    counts = {}
    for r in rows:
        for k in r:
            if k not in ("asin", "price_inr", "url", "observed_date"):
                counts[k] = counts.get(k, 0) + 1
    top = sorted(counts.items(), key=lambda kv: -kv[1])[:12]
    if top:
        print("most common specs: " + ", ".join(f"{k} ({n})" for k, n in top))


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

def from_html(folder, out):
    """Offline mode: search pages -> listing CSV, product pages -> specs CSV.
    observed_date = the day the file was saved."""
    rows, specs_rows = {}, {}
    for f in sorted(Path(folder).glob("*.htm*")):
        soup = BeautifulSoup(f.read_text(encoding="utf-8", errors="ignore"), "html.parser")
        seen = str(date.fromtimestamp(f.stat().st_mtime))
        found, _ = parse_search(soup, f"saved:{f.name}")
        if found:
            laptops = [r for r in found if not not_a_laptop(r)]
            for r in laptops:
                rows.setdefault(r["asin"], {**r, "observed_date": seen})
            print(f"{f.name}: {len(found)} search results, {len(found) - len(laptops)} accessories dropped")
            continue
        asin_input = soup.find("input", id="ASIN")
        canon = re.search(r"/dp/([A-Z0-9]{10})", str(soup.find("link", rel="canonical")))
        asin = (asin_input.get("value") if asin_input else None) or (canon.group(1) if canon else None)
        if not asin:
            print(f"{f.name}: no search results or product ASIN found, skipped"); continue
        specs, price = parse_product(soup)
        specs_rows[asin] = {"asin": asin, **specs, "price_inr": price, "url": f"{BASE}/dp/{asin}",
                            "observed_date": seen}
        print(f"{f.name}: product {asin}, {len(specs)} specs, " + (f"₹{price:,}" if price else "no price"))
    if rows:
        summary(list(rows.values())); save(list(rows.values()), out)
    if specs_rows:
        specs_summary(specs_rows.values()); save_specs(list(specs_rows.values()), specs_path(out))
    if not rows and not specs_rows:
        print("nothing parsed")


def tidy_csv(path):
    """--tidy: applies the current cleaning rules to a listing CSV from an older run (plain titles, brand from
    the title, accessories dropped, per-unit prices out of mrp_inr), keeps the original as
    <name>.before-tidy.csv, and writes the .xlsx. A specs CSV only gets its .xlsx - its values come straight
    from the product page."""
    if path.stem.endswith("_specs"):
        save_specs(list(load_specs(path).values()), path)
        return
    rows = list(load_previous(path)[0].values())
    before = {r["asin"]: (r.get("title"), r.get("brand"), r.get("mrp_inr")) for r in rows}
    kept, dropped = [], []
    for r in rows:
        why = not_a_laptop(tidy(r))
        if why:
            dropped.append((r, why))
        else:
            kept.append(r)
    titles = sum(1 for r in kept if r["title"] != before[r["asin"]][0])
    brands = sum(1 for r in kept if r["brand"] and not before[r["asin"]][1])
    mrps = sum(1 for r in kept if before[r["asin"]][2] and not r["mrp_inr"])
    print(f"{path.name}: {len(rows)} rows -> {len(kept)} laptops")
    print(f"  {len(dropped)} accessories dropped, e.g.:")
    for r, why in dropped[:5]:
        print(f"    {r['asin']} ({why}): {r['title'][:70]}")
    print(f"  brand filled in from the title: {brands}; bold-letter titles made plain: {titles}; "
          f"per-unit prices removed from mrp_inr: {mrps}")
    backup = path.with_name(path.stem + ".before-tidy" + path.suffix)
    if not backup.exists():
        shutil.copy2(path, backup)
        print(f"  original kept as {backup.name}")
    summary(kept)
    save(kept, path)


def main(queries, pages, out, dry, stale_limit=2, start_page=None, delays=DELAYS):
    """Stage 1: search pages -> listing CSV."""
    robots = load_robots()
    if dry:
        print(f"crawl-delay: {robots.crawl_delay or 'none'}; waits cycle {delays} s; each query is followed "
              f"page by page until Next is disabled" + (f" (max {pages} pages)" if pages else "") + ":")
        for q in queries:
            for p in (1, 2, 20):
                u = search_url(q, p)
                print(" ", "ok      " if robots.allowed(u) else "BLOCKED ", u)
        return

    rows, progress, prog_path = load_previous(out)
    if rows:
        print(f"resuming: {len(rows)} rows already in {out.name}, "
              f"{sum(v['done'] for v in progress.values())} queries finished")
    sess = PoliteSession(robots, robots.crawl_delay, delays)

    def mark(q, page, done):
        progress[q] = {"page": page, "done": done}
        prog_path.write_text(json.dumps(progress, indent=1), encoding="utf-8")

    try:
        for qi, q in enumerate(queries):
            if progress.get(q, {}).get("done"):
                print(f"'{q}': already finished, skipped"); continue
            first = progress.get(q, {}).get("page", 0) + 1
            if start_page and qi == 0 and q not in progress:
                first = start_page  # --start-page: for a CSV made before progress files existed
            if first > 1:
                print(f"'{q}': resuming at page {first}")
            stale = 0  # consecutive pages that added no new ASIN
            for p in itertools.count(first):
                soup = sess.soup(search_url(q, p))
                if soup is None:
                    break
                found, (has_next, last) = parse_search(soup, q)
                laptops = [r for r in found if not not_a_laptop(r)]
                new = [r for r in laptops if r["asin"] not in rows]  # a page of only accessories counts as stale
                rows.update((r["asin"], r) for r in new)
                print(f"'{q}' page {p}/{last or '?'}: {len(found)} results, {len(new)} new"
                      + (f", {len(found) - len(laptops)} accessories dropped" if len(laptops) < len(found) else "")
                      + f" (total {len(rows)})")
                save(list(rows.values()), out, quiet=True)  # checkpoint: a crash in hour 3 loses one page
                stale = 0 if new else stale + 1
                if not found or not has_next:
                    print(f"'{q}': " + ("Next is disabled - last page reached" if found else "no results"))
                elif stale_limit and stale >= stale_limit:
                    print(f"'{q}': {stale} pages in a row with no new laptops - moving on")
                elif pages and p >= pages:
                    print(f"'{q}': stopped at --pages {pages}")
                else:
                    mark(q, p, False); continue
                mark(q, p, True); break
    except Stop as e:
        print("STOPPED:", e)
    except KeyboardInterrupt:
        print("interrupted - saving what we have")
    finally:
        if rows:
            summary(list(rows.values()))
            save(list(rows.values()), out)


def specs_main(listing, limit, dry, delays=DELAYS, empty_limit=5):
    """Stage 2: product pages of every ASIN in the listing CSV -> <listing>_specs.csv (specs + price only)."""
    out = specs_path(listing)
    listed = load_previous(listing)[0]
    asins = [a for a, r in listed.items() if not not_a_laptop(tidy(r))]  # older listings still hold accessories
    done = load_specs(out)
    todo = [a for a in asins if a not in done][:limit]
    hours = len(todo) * sum(delays) / len(delays) / 3600
    print(f"{len(asins)} laptops in {listing.name}" + (f" ({len(listed) - len(asins)} accessories skipped)"
                                                       if len(asins) < len(listed) else "")
          + f"; {len(done)} already in {out.name}; {len(todo)} to fetch this run (~{hours:.1f} h at {delays} s waits)")
    robots = load_robots()
    if dry:
        for a in todo[:3]:
            print(" ", "ok      " if robots.allowed(f"{BASE}/dp/{a}") else "BLOCKED ", f"{BASE}/dp/{a}")
        return

    sess, empty = PoliteSession(robots, robots.crawl_delay, delays), 0
    try:
        for i, asin in enumerate(todo, 1):
            url = f"{BASE}/dp/{asin}"
            soup = sess.soup(url)
            specs, price = parse_product(soup) if soup is not None else ({}, None)
            if not specs and price is None:
                # Not saved, so a rerun retries it. Many in a row means the page layout changed or Amazon is
                # serving stripped pages - better to stop than to spend hours collecting blanks.
                empty += 1
                print(f"  {i}/{len(todo)} {asin}: no specs or price found ({empty} in a row)")
                if empty >= empty_limit:
                    raise Stop(f"{empty} product pages in a row had no specs or price - stopping to check")
                continue
            empty = 0
            done[asin] = {"asin": asin, **specs, "price_inr": price, "url": url, "observed_date": str(date.today())}
            save_specs(list(done.values()), out, quiet=True)  # checkpoint after every product
            print(f"  {i}/{len(todo)} {asin}: {len(specs)} specs, " + (f"₹{price:,}" if price else "no price")
                  + f" | {specs.get('brand', '')} {specs.get('model_name', '')}".rstrip())
    except Stop as e:
        print("STOPPED:", e)
    except KeyboardInterrupt:
        print("interrupted - saving what we have")
    finally:
        if done:
            specs_summary(done.values())
            save_specs(list(done.values()), out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # Windows consoles can't print ₹ otherwise
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--queries", nargs="+", default=DEFAULT_QUERIES)
    ap.add_argument("--pages", type=int, default=None,
                    help="optional cap on pages per query (default: follow until Next is disabled)")
    ap.add_argument("--stale-pages", type=int, default=2,
                    help="move to the next query after N pages in a row with no new laptops (0 = never)")
    ap.add_argument("--start-page", type=int, default=None,
                    help="resume the first query at this page (only needed for a CSV without a .progress.json)")
    ap.add_argument("--specs", nargs="?", const="latest", type=str, default=None, metavar="LISTING_CSV",
                    help="stage 2: open every ASIN's product page for specs + price (default: newest listing CSV)")
    ap.add_argument("--limit", type=int, default=None, help="--specs: at most N product pages this run")
    ap.add_argument("--delays", type=float, nargs="+", default=DELAYS,
                    help="seconds between requests, cycled (default: 30 60 120)")
    ap.add_argument("--out", type=Path, default=OUT_DIR / f"amazon_laptops_{date.today()}.csv")
    ap.add_argument("--dry-run", action="store_true", help="only check robots.txt and list the URLs")
    ap.add_argument("--from-html", type=Path, help="parse saved .html pages in this folder; no network")
    ap.add_argument("--tidy", nargs="?", const="latest", default=None, metavar="CSV",
                    help="re-clean an existing CSV with the current rules and write its .xlsx; no network "
                         "(default: newest listing CSV, and its specs CSV if there is one)")
    a = ap.parse_args()
    delays = tuple(a.delays)
    if a.tidy:
        target = latest_listing() if a.tidy == "latest" else Path(a.tidy)
        if target is None or not target.exists():
            sys.exit(f"no CSV found ({a.tidy}); pass its path")
        for csv_path in (target, specs_path(target)):  # a listing's specs CSV, if stage 2 has run
            if csv_path.exists():
                tidy_csv(csv_path)
    elif a.from_html:
        from_html(a.from_html, a.out)
    elif a.specs:
        listing = latest_listing() if a.specs == "latest" else Path(a.specs)
        if listing is None or not listing.exists():
            sys.exit(f"no listing CSV found ({a.specs}); run stage 1 first or pass its path")
        specs_main(listing, a.limit, a.dry_run, delays)
    else:
        main(a.queries, a.pages, a.out, a.dry_run, a.stale_pages, a.start_page, delays)
    sys.exit(0)
