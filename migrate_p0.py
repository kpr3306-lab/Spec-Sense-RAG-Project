"""Adds the roadmap's P0 columns (all NULL = unknown). Safe to re-run."""
import sqlite3
from pathlib import Path
DB = Path(__file__).resolve().parent.parent / "data" / "specsense.db"
P0 = {  # column: type
    "ram_layout": "TEXT",            # soldered / SO-DIMM / mixed / LPCAMM2
    "ram_channel_config": "TEXT",    # single / dual / flex / unknown
    "ram_free_slots": "INTEGER",
    "storage_free_slots": "INTEGER",
    "display_surface": "TEXT",       # glossy / matte / anti-glare
    "usb_c_pd_input_w": "REAL",
    "service_centre_evidence": "TEXT",
    "warranty_battery_months": "INTEGER",
    "tested_battery_workload": "TEXT",
    "image_path": "TEXT",           # local cached file under data/images/
    "image_source_url": "TEXT",     # page the image came from
    "image_verified_date": "TEXT",
    "price_note": "TEXT",           # e.g. config mismatch warnings
}
con = sqlite3.connect(DB)
have = {r[1] for r in con.execute("PRAGMA table_info(laptops)")}
for c, t in P0.items():
    if c not in have:
        con.execute(f"ALTER TABLE laptops ADD COLUMN {c} {t}")
        print("added", c)
con.commit(); con.close()
