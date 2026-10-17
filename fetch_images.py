"""Fetch official product images.  Run on YOUR machine (needs internet):  python3 fetch_images.py [--limit N] [--dry-run]
For each SKU with a source_url, reads the page's og:image / twitter:image, saves it to data/images/<sku>.<ext>
and records image_path + image_source_url + image_verified_date. Only the image columns are touched.
Caveats: (1) listing pages (e.g. HP category URLs) give a generic image, not the exact SKU -> those are skipped
unless the URL looks like a product page; (2) manufacturer images are copyrighted - keep for personal/academic
demo use and keep the source URL visible (the UI does)."""
import re, sqlite3, sys, urllib.request, html as H
from datetime import date
from pathlib import Path
from urllib.parse import urljoin
import recommendation_engine as R

OUT = Path(__file__).resolve().parent.parent / "data" / "images"
UA = {"User-Agent": "Mozilla/5.0 (SpecSense academic project)"}
LISTING = re.compile(r"/listings/|/product-compare|/laptop-price/|\?(segment|graphics|memstd|processortype)=|processor_type-|/laptops/?$")

def find_image(page_html, base_url):
    for pat in (r'<meta[^>]+property=["\']og:image(?::secure_url)?["\'][^>]+content=["\']([^"\']+)',
                r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']',
                r'<meta[^>]+name=["\']twitter:image["\'][^>]+content=["\']([^"\']+)'):
        m = re.search(pat, page_html, re.I)
        if m: return urljoin(base_url, H.unescape(m.group(1)))
    return None

def get(url, binary=False):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20) as r:
        return r.read() if binary else r.read().decode("utf-8", "ignore")

def main(limit=None, dry=False):
    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(R.DB_PATH); done = 0
    for l in R.load_laptops():
        if limit is not None and done >= limit: break
        url = l.get("source_url") or ""
        if not url or LISTING.search(url) or l.get("image_path"): continue
        try:
            img = find_image(get(url), url)
            if not img: print("no image:", l["sku_id"]); continue
            ext = (re.search(r"\.(jpe?g|png|webp)(?:\?|$)", img, re.I) or [None, "jpg"])[1].lower()
            path = OUT / f"{re.sub(r'[^A-Za-z0-9_.-]', '_', l['sku_id'])}.{ext}"
            if dry: print("would save", img, "->", path.name); done += 1; continue
            path.write_bytes(get(img, True))
            con.execute("UPDATE laptops SET image_path=?, image_source_url=?, image_verified_date=? WHERE sku_id=?",
                        (str(path.relative_to(OUT.parent.parent)), url, str(date.today()), l["sku_id"]))
            con.commit(); done += 1; print("saved", l["sku_id"])
        except Exception as e:
            print("failed", l["sku_id"], e)
    print("done:", done)

if __name__ == "__main__":
    a = sys.argv; main(int(a[a.index("--limit") + 1]) if "--limit" in a else None, "--dry-run" in a)
