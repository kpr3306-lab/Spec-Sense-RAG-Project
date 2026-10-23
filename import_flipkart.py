"""Flipkart listing -> SpecSense catalogue.  python3 import_flipkart.py [data/flipkart_laptops_YYYY-MM-DD.csv] [--apply]
Without --apply it only reports. Default CSV: the newest one scrape_flipkart.py wrote.
Laptops only (tablets, SSDs, monitors, desktop parts are dropped). Every value comes from Flipkart's title or spec
bullets; anything not stated stays NULL (unknown). Price = Flipkart's current selling price; the MRP is not imported.
A blank rating stays blank. sku_id = Flipkart's product id, so re-running updates the same rows and never touches
rows from other sources. If <listing>_specs.csv exists (scrape_flipkart.py --specs), its product-page
Specifications table fills the fields the listing left unknown (weight, resolution, ports, battery ...)."""
import csv, re, sqlite3, sys
from pathlib import Path
from recommendation_engine import DB_PATH
from scrape_amazon import load_specs
from scrape_flipkart import latest_listing, specs_path

# Every column the engine and app read. A missing table is created with these; a missing column is added (NULL).
COLUMNS = """sku_id brand model_name region source_url source_note last_verified_date exact_config_verified confidence
data_confidence_score workload_tags colour observed_price_inr msrp_inr retailer_name price_source_url
price_last_checked_date price_note cpu_model cpu_cores cpu_threads cpu_p_cores cpu_e_cores cpu_base_clock_ghz
cpu_boost_clock_ghz cpu_architecture cpu_cache_mb cpu_tdp_w npu_tops gpu_model gpu_type gpu_architecture gpu_vram_gb
gpu_vram_type gpu_memory_bus_bit gpu_tgp_w gpu_mux_switch gpu_advanced_optimus ram_gb ram_type ram_speed_mhz
ram_upgradeable ram_max_gb ram_slots ram_soldered_gb ram_layout ram_channel_config ram_free_slots storage_gb
storage_type storage_interface storage_slots storage_upgradeable storage_free_slots display_size_in display_resolution
display_aspect_ratio display_panel_type display_refresh_hz display_brightness_nits display_color_gamut
display_color_depth display_response_ms display_hdr display_vrr display_surface touch_screen weight_kg
dimensions_width_mm dimensions_depth_mm dimensions_thickness_mm build_material battery_wh battery_life_claimed_hrs
tested_battery_hrs tested_battery_workload usb_c_charging usb_c_pd_input_w fast_charging charger_watt usb_a_count
usb_a_speed usb_c_count usb_c_speed thunderbolt_usb4 usb_c_display_output hdmi_version sd_card_reader ethernet_port
wifi_gen bluetooth_version webcam_resolution os warranty_years warranty_type warranty_battery_months onsite_support
accidental_damage_option service_network_coverage service_centre_evidence spare_part_availability repairability_rating
box_contents image_path image_primary_url image_source image_source_url image_verified_date
rating rating_count highlights model_family""".split()
NOT_A_LAPTOP = re.compile(r"\b(tablet|all-in-one|aio|desktop|monitor)\b", re.I)
# Where the processor starts in a title head: the words before it are the model family (= what variants share).
CPU_START = re.compile(r"\s(?=(?:Intel|INTEL|AMD|Apple M\d|Snapdragon|Qualcomm|MediaTek|Mediatek|Ryzen|Celeron|Pentium|"
                       r"Core [iI]\d|Core Ultra|M\d|A18)\b)")
OS_WORDS = re.compile(r"Windows|mac ?OS|Mac OS|Chrome|Tahoe|Sonoma|Sequoia|Android|DOS|Ubuntu|Prime OS")


def parse(r):
    """One listing row -> catalogue fields, or None if it isn't a laptop.
    Titles look like 'HP Victus Intel Core i5 13th Gen 13420 H - (16 GB/512 GB SSD/Windows 11 Home/6 GB Graphics/
    NVIDIA GeForce RTX 3050/144 Hz) fa1351TX Gaming Laptop'; bullets like '16 GB DDR4 RAM | 39.62 cm (15.6 Inch) Display'."""
    title, bullets = r["title"].removesuffix("..."), (r["highlights"] or "").split(" | ")
    config = re.search(r" - \(([^)]*)", title)
    parts = [p.strip() for p in config.group(1).split("/")] if config else []
    if config and not title[config.end():].startswith(")"):
        parts = parts[:-1]  # title cut off inside the brackets: the last part is incomplete ("NVIDIA Ge...")

    def bullet(pattern):
        return next((m for b in bullets if (m := re.search(pattern, b))), None)

    ram_b = bullet(r"(\d+) GB (.+?) RAM")
    ram = (re.match(r"(\d+) GB", parts[0]) if parts else None) or ram_b
    if not ram or NOT_A_LAPTOP.search(title):
        return None
    store = next((m for p in parts[1:2] + bullets if (m := re.search(r"(\d+(?:\.\d+)?) (GB|TB) (SSD|EMMC|HDD)", p, re.I))), None)
    gpu = next((i for i, p in enumerate(parts) if re.fullmatch(r"\d+ GB Graphics", p)), None)
    gpu_name = parts[gpu + 1] if gpu is not None and gpu + 1 < len(parts) else None
    hz = next((m for p in parts if (m := re.fullmatch(r"(\d+) Hz", p, re.I))), None)
    os_b = bullet(r"^(?:64 bit )?(.+?) Operating System")
    cpu = bullet(r"^(.+?) Processor\b(.*)$")
    size = bullet(r"\(([\d.]+) [Ii]nch\)")
    warranty = bullet(r"(\d+) Years? (.*?)\b(?:Warranty|Service)")
    brand = r["brand"] or None
    # the UI shows brand + model, so drop the brand from the title ("HP HP Victus 15" -> "Victus 15")
    model = (re.sub(rf"^(?:{re.escape(brand)}\s+)+", "", title, flags=re.I) if brand else "") or title
    head = model.split(" - (")[0]  # 'Victus Intel Core i5 13th Gen 13420 H' -> family 'Victus', cpu 'Intel Core ...'
    family, *title_cpu = CPU_START.split(" " + head, 1)  # leading space: a head that starts with the CPU -> ""
    return {
        "sku_id": r["pid"], "brand": brand, "model_name": model, "model_family": family.strip(" ,") or head,
        "ram_gb": int(ram.group(1)), "ram_type": ram_b.group(2) if ram_b else None,
        "storage_gb": (float(store.group(1)) * (1024 if store.group(2).upper() == "TB" else 1)) if store else None,
        "storage_type": {"SSD": "SSD", "EMMC": "eMMC", "HDD": "HDD"}[store.group(3).upper()] if store else None,
        "os": re.sub(r"^(Tahoe|Sonoma|Sequoia)$", r"macOS \1",  # Apple titles say just "Tahoe"
                     next((p for p in parts if OS_WORDS.search(p)), None) or (os_b.group(1) if os_b else "")) or None,
        "cpu_model": (cpu.group(1) + cpu.group(2)).strip() if cpu else (title_cpu[0] if title_cpu else None),
        "gpu_type": "Discrete" if gpu is not None else None,  # Flipkart lists 'N GB Graphics' only for a dedicated GPU
        "gpu_vram_gb": int(parts[gpu].split()[0]) if gpu is not None else None,
        "gpu_model": gpu_name if gpu_name and not re.search(r"\d+ (Hz|GHz|W)\b", gpu_name, re.I) else None,
        "display_size_in": float(size.group(1)) if size else None,
        "display_refresh_hz": int(hz.group(1)) if hz else None,
        "touch_screen": 1 if any("Touchscreen" in b for b in bullets) else None,
        "warranty_years": int(warranty.group(1)) if warranty else None,
        "warranty_type": (warranty.group(2).strip() or None) if warranty else None,
        "onsite_support": 1 if warranty and "Onsite" in warranty.group(2) else None,
        "observed_price_inr": float(r["price_inr"]) if r["price_inr"] else None,
        "retailer_name": "Flipkart", "price_source_url": r["url"], "source_url": r["url"],
        "price_last_checked_date": r["observed_date"], "last_verified_date": r["observed_date"], "region": "India",
        "source_note": "Flipkart listing page (title + spec bullets)",
        "rating": float(r["rating"]) if r["rating"] else None,
        "rating_count": int(float(r["rating_count"])) if r["rating_count"] else None,
        "highlights": r["highlights"] or None,
    }


def parse_specs(s):
    """One row of <listing>_specs.csv -> catalogue fields. Keys are Flipkart's spec labels ('screen_type':
    'WUXGA (1920x1200) IPS 400nits Glossy, 72% NTSC, 60Hz'); only what a value states is kept."""
    def num(key, pattern=r"(\d+(?:\.\d+)?)", text=None):
        m = re.search(pattern, text if text is not None else s.get(key) or "", re.I)
        return float(m.group(1)) if m else None

    def yes(key):
        v = (s.get(key) or "").lower()
        return 1 if v.startswith("yes") else 0 if v.startswith("no") else None

    screen, usb, power = s.get("screen_type") or "", s.get("usb_port") or "", s.get("power_supply") or ""
    # '2 x USB 3.2 Gen 1, 1 x USB-C 3.2 Gen 1 (...)'; anchored at a comma so 'Gen 2x2' isn't read as a count
    a = c = None
    for n, port in re.findall(r"(?:^|,)\s*(\d+)\s*x\s*([^,]+)", usb, re.I):
        if re.search(r"Type[- ]?C|USB[- ]?C|Thunderbolt|USB ?4", port, re.I):
            c = (c or 0) + int(n)
        elif "USB" in port.upper():
            a = (a or 0) + int(n)
    if a is not None or c is not None:
        a, c = a or 0, c or 0  # the row lists every USB port, so a type it doesn't name is absent
    dims = re.findall(r"\d+(?:\.\d+)?", s.get("dimensions") or "") if "mm" in (s.get("dimensions") or "") else []
    res = re.search(r"(\d{3,4})\s*x\s*(\d{3,4})", (s.get("screen_resolution") or "") + " " + screen)
    panel = re.search(r"\b(Mini[- ]?LED|AMOLED|OLED|IPS|TN|VA|LCD)\b", screen)
    gamut = re.search(r"\d+%\s*(?:sRGB|DCI-?P3|NTSC|Adobe ?RGB)", screen, re.I)
    wifi = re.search(r"Wi-?Fi\s*(\d+E?)|802\.11\s*(be|ax|ac)", s.get("wireless_lan") or "", re.I)
    wifi = (wifi.group(1) or {"be": "7", "ax": "6", "ac": "5"}[wifi.group(2).lower()]) if wifi else None
    gpu = s.get("graphic_processor") or ""
    ram, exp = num("ram", r"(\d+)\s*GB"), num("expandable_memory", r"(\d+)\s*GB")
    cam = re.sub(r"^Yes,?\s*", "", s.get("web_camera") or "")
    return {
        "weight_kg": num("weight", r"([\d.]+)\s*kg"),
        **dict(zip(["dimensions_width_mm", "dimensions_depth_mm", "dimensions_thickness_mm"],
                   map(float, dims) if len(dims) == 3 else [None] * 3)),
        "display_resolution": f"{res.group(1)}x{res.group(2)}" if res else None,
        "display_panel_type": panel.group(1) if panel else None,
        "display_brightness_nits": num("brightness") or num(None, r"(\d+)\s*nits", screen),
        "display_refresh_hz": num("refresh_rate") or num(None, r"(\d+)\s*Hz", screen),
        "display_color_gamut": gamut.group(0) if gamut else None,
        "touch_screen": yes("touchscreen"),
        "colour": s.get("color"),
        "cpu_cores": num("number_of_cores", r"^(\d+)$"),
        "gpu_model": gpu or None,
        "gpu_type": "Integrated" if "integrated" in gpu.lower() else None,
        "ram_max_gb": exp,
        "ram_upgradeable": (int(exp > ram) if exp and ram else
                            0 if "no slots" in (s.get("memory_slots") or "").lower() else None),
        "usb_a_count": a, "usb_c_count": c,
        "thunderbolt_usb4": 1 if re.search(r"Thunderbolt|USB ?4", usb, re.I) else None,
        "usb_c_charging": 1 if re.search(r"USB[- ]?C|Type[- ]?C", power, re.I) or re.search(r"Power Delivery|\bPD\b", usb) else None,
        "charger_watt": num(None, r"(\d+)\s*W\b", power),
        "hdmi_version": num("hdmi_port", r"HDMI\s*(\d+(?:\.\d+)?)"),
        "ethernet_port": yes("ethernet"), "sd_card_reader": yes("multi_card_slot"),
        "wifi_gen": f"Wi-Fi {wifi}" if wifi else None,
        "bluetooth_version": num("bluetooth"),
        "webcam_resolution": cam if cam and not cam.lower().startswith("no") else None,
        "battery_life_claimed_hrs": num("battery_backup"),
        "battery_wh": num(None, r"(\d+(?:\.\d+)?)\s*Wh", " ".join(v for k, v in s.items() if "battery" in k)),
        "warranty_years": num("domestic_warranty", r"(\d+)\s*Year") or num("warranty_summary", r"(\d+)\s*Year"),
    }


def main(path, apply):
    rows = list(csv.DictReader(open(path, encoding="utf-8-sig")))
    parsed = [p for p in map(parse, rows) if p]
    print(f"{path.name}: {len(rows)} rows -> {len(parsed)} laptops ({len(rows) - len(parsed)} tablets/parts/unparseable dropped)")
    specs = load_specs(specs_path(path), "pid")
    for p in parsed:
        if p["sku_id"] in specs:  # the listing's own values win; the spec table only fills what it left unknown
            p.update({k: v for k, v in parse_specs(specs[p["sku_id"]]).items() if v is not None and p.get(k) is None})
            p["source_note"] = "Flipkart listing page + product page Specifications table"
    print(f"  product-page specs for {sum(1 for p in parsed if p['sku_id'] in specs)} of them ({specs_path(path).name})")
    for k in ["observed_price_inr", "rating", "ram_gb", "storage_gb", "cpu_model", "os", "display_size_in", "gpu_model",
              "warranty_years", "weight_kg", "display_resolution", "usb_a_count", "battery_life_claimed_hrs"]:
        print(f"  {k:24} known for {sum(1 for p in parsed if p.get(k) is not None):4}")
    if not apply:
        print("dry run - add --apply to write", DB_PATH); return
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.execute("CREATE TABLE IF NOT EXISTS laptops (sku_id TEXT PRIMARY KEY)")
    have = {c[1] for c in con.execute("PRAGMA table_info(laptops)")}
    for c in COLUMNS:
        if c not in have:
            con.execute(f"ALTER TABLE laptops ADD COLUMN {c}")
    existing = {r[0] for r in con.execute("SELECT sku_id FROM laptops")}
    for p in parsed:
        ks = [k for k in p if k != "sku_id"]
        if p["sku_id"] in existing:
            con.execute(f"UPDATE laptops SET {', '.join(k + '=?' for k in ks)} WHERE sku_id=?", [p[k] for k in ks] + [p["sku_id"]])
        else:
            con.execute(f"INSERT INTO laptops ({', '.join(p)}) VALUES ({', '.join('?' * len(p))})", list(p.values()))
    con.commit(); con.close()
    print(f"wrote {len(parsed)} laptops ({sum(1 for p in parsed if p['sku_id'] in existing)} updated) -> {DB_PATH}")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--apply"]
    csv_path = Path(args[0]) if args else latest_listing()
    if csv_path is None or not csv_path.exists():
        sys.exit("no Flipkart listing CSV found; run scrape_flipkart.py first or pass its path")
    main(csv_path, "--apply" in sys.argv)
