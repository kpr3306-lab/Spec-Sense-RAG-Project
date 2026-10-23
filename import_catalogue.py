"""Validated bulk-add of exact SKUs.  python3 import_catalogue.py new_skus.csv [--apply]
Without --apply it only reports problems. Blank cells stay NULL (unknown); 0 in a spec column that can't be 0 is rejected."""
import csv, sqlite3, sys
from recommendation_engine import DB_PATH
REQUIRED = ["sku_id", "brand", "model_name", "region", "source_url", "last_verified_date", "exact_config_verified"]
NOT_ZERO = ["ram_gb", "storage_gb", "weight_kg", "battery_wh", "display_size_in", "display_brightness_nits", "display_refresh_hz", "cpu_cores"]

def main(path, apply):
    con = sqlite3.connect(DB_PATH)
    cols = {r[1] for r in con.execute("PRAGMA table_info(laptops)")}
    existing = {r[0] for r in con.execute("SELECT sku_id FROM laptops")}
    good, bad = [], []
    for n, row in enumerate(csv.DictReader(open(path, encoding="utf-8-sig")), 2):
        row = {k: (v.strip() or None) for k, v in row.items() if k in cols}
        errs = [f"missing {c}" for c in REQUIRED if not row.get(c)]
        errs += [f"{c}=0 (use blank for unknown)" for c in NOT_ZERO if row.get(c) in ("0", "0.0")]
        if row.get("sku_id") in existing: errs.append("duplicate SKU already in catalogue")
        if row.get("region") and row["region"] != "India": errs.append("region is not India — confirm intentional")
        (bad if errs else good).append((n, row, errs))
    for n, row, errs in bad: print(f"line {n} {row.get('sku_id')}: " + "; ".join(errs))
    print(f"{len(good)} valid, {len(bad)} rejected")
    if apply:
        for _, row, _ in good:
            ks = list(row); con.execute(f"INSERT INTO laptops ({','.join(ks)}) VALUES ({','.join('?'*len(ks))})", [row[k] for k in ks])
        con.commit(); print("inserted", len(good))

if __name__ == "__main__":
    main(sys.argv[1], "--apply" in sys.argv)
