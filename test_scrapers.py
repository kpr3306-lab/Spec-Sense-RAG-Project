"""Offline checks for the scrapers' parsers and robots handling: python test_scrapers.py (or pytest). No network."""
import json

from bs4 import BeautifulSoup

import api
import import_flipkart as imp
import scrape_amazon as amz
import scrape_flipkart as fk

CARD = """<div data-id="COMH1"><a href="/hp-15/p/itm1?pid=COMH1&lid=x&otracker=browse">
<div>HP 15 Intel Core 5 120U - (16 GB/512 GB SSD/Windows 11 Home) Thin and Light Laptop</div>
<div>4.1</div><span>655 Ratings</span><span>&amp;</span><span>51 Reviews</span>
<ul><li>Intel Core 5 Processor</li><li>16 GB DDR5 RAM</li></ul>
<div>&#8377;79,990</div><div>&#8377;<!-- -->2,55,379</div><span>39% off</span>
<div>Upto</div><div>&#8377;58,650</div><div>Off on Exchange</div></a></div>"""


def test_flipkart_card():
    r, = fk.parse_listing(BeautifulSoup(CARD, "html.parser"), "laptops/hp~brand")
    assert (r["price_inr"], r["mrp_inr"]) == (79990, 255379)  # the exchange-offer ₹58,650 is not a price
    assert (r["rating"], r["rating_count"], r["brand"]) == (4.1, 655, "HP")
    assert r["highlights"] == "Intel Core 5 Processor | 16 GB DDR5 RAM"
    assert r["url"] == "https://www.flipkart.com/hp-15/p/itm1?pid=COMH1"  # tracking params dropped


def test_flipkart_product():
    state = {"a": [{"label_0": {"value": {"text": "Processor Name"}}, "label_1": {"value": {"text": ["Ryzen 3"]}}},
                   {"label_0": {"value": {"text": "Operating System"}}, "label_1": {"value": {"text": ["Windows 11"]}}},
                   {"label_0": {"value": {"text": "Operating System"}}, "label_1": {"value": {"text": ["Windows 11 Home"]}}},
                   {"label_0": {"value": {"text": "Country of Origin"}}, "label_1": {"value": {"text": ["India"]}}},
                   {"label_0": {"value": {"text": "₹59,740"}}, "label_1": {"value": {"text": "with Bank offer"}}}]}
    ld = {"@type": "Product", "sku": "COMH1", "offers": {"price": 62990, "priceCurrency": "INR"}}
    html = (f'<script type="application/ld+json">{json.dumps([ld])}</script>'
            f"<script>window.__INITIAL_STATE__ = {json.dumps(state)};</script>")
    specs, price = fk.parse_product(BeautifulSoup(html, "html.parser"))
    assert specs == {"processor_name": "Ryzen 3", "operating_system": "Windows 11 Home"}
    assert price == 62990
    ld["offers"]["priceCurrency"] = "USD"
    assert fk.product_price(BeautifulSoup(f'<script type="application/ld+json">{json.dumps(ld)}</script>',
                                          "html.parser")) is None


def test_flipkart_pages():
    assert fk.laptop_page("https://www.flipkart.com/laptops/hp~brand/pr?sid=6bo,b5g")
    assert fk.laptop_page("https://www.flipkart.com/q/best-laptops-under-rs-40000")
    assert not fk.laptop_page("https://www.flipkart.com/q/14-inch-laptop-bags")
    assert not fk.laptop_page("https://www.flipkart.com/hi/laptops/hp~brand/pr?sid=6bo,b5g")


def test_redirect_to_disallowed_url_is_not_fetched():
    robots = amz.Robots("User-agent: *\nDisallow: /search?\nDisallow: *page=*")
    assert not robots.allowed("https://www.flipkart.com/laptops/pr?sid=6bo,b5g&page=2")
    sess, fetched = amz.PoliteSession(robots, 0, delays=(0,), markers=()), []

    class Redirect:
        status_code, is_redirect, headers = 302, True, {"Location": "/search?q=laptop"}

    sess.s.get = lambda url, **kw: fetched.append(url) or Redirect()
    assert sess.get("https://www.flipkart.com/q/laptops") is None
    assert fetched == ["https://www.flipkart.com/q/laptops"]


def test_amazon_accessories():
    assert amz.not_a_laptop({"price_inr": 508.0, "title": "Saco Screen Protector for Acer"})
    assert amz.not_a_laptop({"price_inr": 10599.0, "title": "Dell WB5023 Webcam - 60 fps"})
    assert not amz.not_a_laptop({"price_inr": 39990.0, "title": "Acer Aspire Lite Metal (2026), Backlit Keyboard AMD"})
    assert amz.brand_from_title("𝗗𝗲𝗹𝗹Laptop Latitude 5470") == "Dell"


def test_flipkart_import():
    row = {"pid": "COMG1", "brand": "HP", "price_inr": "85999.0", "mrp_inr": "120000.0", "rating": "", "rating_count": "",
           "url": "https://www.flipkart.com/x/p/itm1?pid=COMG1", "observed_date": "2026-10-22",
           "title": "HP HP Victus Intel Core i5 13th Gen 13420 H - (16 GB/1 TB SSD/Windows 11 Home/6 GB Graphics/"
                    "NVIDIA GeForce RTX 3050/144 Hz) fa1351TX Gaming Laptop",
           "highlights": "Intel Core i5 Processor (13th Gen) | 16 GB DDR4 RAM | 39.62 cm (15.6 Inch) Display | "
                         "1 Year Onsite Warranty"}
    p = imp.parse(row)
    assert (p["model_family"], p["cpu_model"], p["ram_gb"], p["ram_type"]) == ("Victus", "Intel Core i5 (13th Gen)", 16, "DDR4")
    assert (p["storage_gb"], p["gpu_type"], p["gpu_vram_gb"], p["gpu_model"]) == (1024, "Discrete", 6, "NVIDIA GeForce RTX 3050")
    assert (p["display_size_in"], p["display_refresh_hz"], p["warranty_years"], p["onsite_support"]) == (15.6, 144, 1, 1)
    assert p["observed_price_inr"] == 85999 and "msrp_inr" not in p  # current price only, never the MRP
    assert p["rating"] is None and p["rating_count"] is None  # blank stays blank
    cut = imp.parse({**row, "title": "HP Victus Intel Core i5 - (16 GB/512 GB SSD/Windows 11 Home/6 GB Graphics/NVIDIA Ge..."})
    assert cut["gpu_model"] is None and cut["gpu_vram_gb"] == 6  # the cut-off part is dropped, not stored half
    assert imp.parse({**row, "title": "Lenovo Tab 4 GB RAM 64 GB ROM 10.1 inch Tablet", "highlights": "4 GB LPDDR4X RAM"}) is None


def test_flipkart_spec_table_import():
    p = imp.parse_specs({"weight": "1.23 Kg", "dimensions": "287 x 200 x 18.6 mm", "screen_resolution": "1366 x 768 Pixel",
                         "screen_type": "HD, TN 250nits Anti-glare 60Hz", "touchscreen": "No", "number_of_cores": "8",
                         "usb_port": "2 x USB 3.2 Gen 1, 1 x USB-C 3.2 Gen 1 (support data transfer, Power Delivery and DisplayPort)",
                         "hdmi_port": "1 x HDMI 1.4b", "wireless_lan": "802.11ax 2x2", "bluetooth": "v5.1",
                         "ethernet": "No Onboard Ethernet", "power_supply": "45W USB-C (3-pin)", "battery_backup": "Upto 8 hours"})
    assert (p["weight_kg"], p["dimensions_thickness_mm"], p["display_resolution"], p["display_panel_type"]) == (1.23, 18.6, "1366x768", "TN")
    assert (p["display_brightness_nits"], p["display_refresh_hz"], p["touch_screen"], p["cpu_cores"]) == (250, 60, 0, 8)
    assert (p["usb_a_count"], p["usb_c_count"], p["usb_c_charging"], p["charger_watt"]) == (2, 1, 1, 45)
    assert (p["hdmi_version"], p["wifi_gen"], p["bluetooth_version"], p["ethernet_port"]) == (1.4, "Wi-Fi 6", 5.1, 0)
    assert p["battery_life_claimed_hrs"] == 8 and p["battery_wh"] is None  # hours stated, Wh not: stays unknown
    q = imp.parse_specs({"usb_port": "2x USB-C (USB 5Gbps), 1x Headphone / microphone combo jack (3.5mm), USB 3.2 Gen 2x2",
                         "memory_slots": "Memory soldered to systemboard, no slots, dual-channel"})
    assert (q["usb_a_count"], q["usb_c_count"], q["ram_upgradeable"]) == (0, 2, 0)  # 'Gen 2x2' is not a port count
    assert imp.parse_specs({})["usb_a_count"] is None and imp.parse_specs({})["weight_kg"] is None  # nothing stated -> unknown


def test_model_search_returns_all_variants():
    L = [{"sku_id": "A1", "brand": "HP", "model_name": "Victus i5 - (16 GB)", "model_family": "Victus", "observed_price_inr": 90000},
         {"sku_id": "A2", "brand": "HP", "model_name": "Victus i7 - (32 GB)", "model_family": "Victus", "observed_price_inr": 80000},
         {"sku_id": "B1", "brand": "HP", "model_name": "Pavilion i5", "model_family": "Pavilion", "observed_price_inr": 70000}]
    (name, vs), = api.variants(L, "a1")  # one SKU -> every variant of its model, cheapest first
    assert name == "HP Victus" and [v["sku_id"] for v in vs] == ["A2", "A1"]
    assert len(api.variants(L, "hp")) == 2 and api.variants(L, "dell") == []


if __name__ == "__main__":
    for name, test in list(globals().items()):
        if name.startswith("test_"):
            test(); print("ok", name)
