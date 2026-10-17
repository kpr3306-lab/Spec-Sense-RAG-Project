"""
SpecSense MVP4 — Accessory intelligence + hidden-cost calculation.

Maps workload/hardware gaps to Essential / Recommended / Optional accessories
(blueprint §7), checking compatibility against the laptop's actual specs and
box contents before recommending anything, then rolls essential + recommended
items into a "total setup cost" alongside the laptop's own price
(blueprint's "hidden-cost calculation").

Rule: never recommend an accessory merely because it exists — every
recommendation below carries a reason and a compatibility check.

Depends on: specsense.db (MVP1), chroma_db/ + knowledge_base/ (MVP2, now
including the accessory_knowledge collection), recommendation_engine.py (MVP3).
"""

from recommendation_engine import (
    load_laptops, load_kb, kb_query, hard_filter, score_candidates, rerank_diverse,
)

# Illustrative typical prices (INR) — NOT live/verified pricing. Flag these for
# refresh against real retailer prices before using in a real cost estimate,
# same data-quality caveat as the laptop dataset itself.
ACCESSORY_CATALOG = {
    "usb_hub_basic":        {"name": "USB-C multiport hub (USB-A + HDMI)",  "price_inr": 1500},
    "usb_dock_thunderbolt": {"name": "Thunderbolt/USB4 dock",               "price_inr": 6500},
    "precision_mouse":      {"name": "Precision wired/wireless mouse",      "price_inr": 1200},
    "stylus_matched":       {"name": "Pen-protocol-matched stylus",         "price_inr": 5500},
    "external_ssd_1tb":     {"name": "1TB USB-C external SSD",              "price_inr": 6000},
    "laptop_stand":         {"name": "Adjustable laptop stand",             "price_inr": 1800},
    "external_monitor":     {"name": "24\" external monitor",               "price_inr": 12000},
    "data_usb_cable":       {"name": "Data-capable USB-A/C cable",          "price_inr": 350},
    "usb_a_adapter":        {"name": "USB-C to USB-A adapter",              "price_inr": 700},
    "ethernet_adapter":     {"name": "USB-C to Ethernet adapter",           "price_inr": 900},
    "cooling_pad":          {"name": "Laptop cooling pad",                  "price_inr": 1500},
}


def _kb_reason(kb_collection, kb_vectorizer, query_text):
    hits = kb_query(kb_collection, kb_vectorizer, query_text, k=1, collection_filter="accessory_knowledge")
    return hits[0]["doc_id"] if hits else None


def recommend_accessories(laptop, req, kb_collection, kb_vectorizer):
    """Returns a list of {key, tier, reason, evidence, price_inr}."""
    recs = []
    box = (laptop.get("box_contents") or "").lower()

    # --- USB-A availability / hub ---
    needs_usb_a = req.get("usb_a_required") or req.get("embedded_dev")
    if needs_usb_a and laptop.get("usb_a_count") == 0:
        tier = "Essential" if req.get("usb_a_required") else "Essential"
        recs.append({
            "key": "usb_a_adapter", "tier": tier,
            "reason": "You need USB-A connectivity but this laptop has no USB-A port.",
            "evidence": _kb_reason(kb_collection, kb_vectorizer, "USB-A availability hub adapter"),
        })

    # --- Many peripherals -> hub/dock ---
    if req.get("many_peripherals"):
        total_ports = laptop["usb_a_count"] + laptop["usb_c_count"]
        if total_ports < 3:
            key = "usb_dock_thunderbolt" if laptop["thunderbolt_usb4"] else "usb_hub_basic"
            recs.append({
                "key": key, "tier": "Recommended",
                "reason": f"Only {total_ports} total USB ports, but you'll be connecting several peripherals.",
                "evidence": _kb_reason(kb_collection, kb_vectorizer, "USB hub dock limited ports many peripherals"),
            })

    # --- CAD/engineering -> precision mouse ---
    if "cad_engineering" in laptop["workload_tags_list"] and "cad_engineering" in (
        req.get("required_workloads", []) + req.get("soft_workloads", [])
    ):
        if "mouse" not in box:
            recs.append({
                "key": "precision_mouse", "tier": "Essential",
                "reason": "CAD work needs precise click/scroll control a trackpad can't reliably give.",
                "evidence": _kb_reason(kb_collection, kb_vectorizer, "precision mouse CAD design work"),
            })

    # --- Digital notes -> stylus (only if the display can actually take one) ---
    if req.get("digital_notes"):
        if laptop["touch_screen"] and "stylus" not in box and "pen" not in box:
            recs.append({
                "key": "stylus_matched", "tier": "Recommended",
                "reason": "Touchscreen present but no stylus included in the box.",
                "evidence": _kb_reason(kb_collection, kb_vectorizer, "stylus pen digital note taking touchscreen"),
            })
        elif not laptop["touch_screen"]:
            recs.append({
                "key": None, "tier": "Limitation",
                "reason": "This display isn't a touchscreen, so it can't support a stylus at all — "
                          "digital note-taking needs a touch+pen-capable display instead.",
                "evidence": _kb_reason(kb_collection, kb_vectorizer, "stylus pen digital note taking touchscreen"),
            })

    # --- Large datasets (ML/DL, content creation) -> external SSD ---
    workloads = set(req.get("required_workloads", []) + req.get("soft_workloads", []))
    if workloads & {"ml_dl", "content_creation"}:
        dataset_threshold_gb = req.get("dataset_size_gb", laptop["storage_gb"])
        if laptop["storage_gb"] <= dataset_threshold_gb:
            recs.append({
                "key": "external_ssd_1tb", "tier": "Recommended",
                "reason": f"{laptop['storage_gb']}GB internal storage is tight for large ML/DL or media datasets.",
                "evidence": _kb_reason(kb_collection, kb_vectorizer, "external SSD large datasets storage"),
            })

    # --- Desk-based heavy work -> stand + monitor ---
    if req.get("desk_based"):
        recs.append({
            "key": "laptop_stand", "tier": "Optional",
            "reason": "Improves ergonomics and cooling airflow for long desk-bound sessions.",
            "evidence": _kb_reason(kb_collection, kb_vectorizer, "laptop stand ergonomics desk work"),
        })
        recs.append({
            "key": "external_monitor", "tier": "Optional",
            "reason": "Extra screen real estate helps multitasking during desk-based heavy work.",
            "evidence": _kb_reason(kb_collection, kb_vectorizer, "external monitor desk based heavy work"),
        })

    # --- Embedded/hobbyist dev boards (ESP32/Arduino) -> data cable ---
    if req.get("embedded_dev"):
        recs.append({
            "key": "data_usb_cable", "tier": "Essential",
            "reason": "Many bundled USB cables are charge-only and won't flash firmware to a dev board.",
            "evidence": _kb_reason(kb_collection, kb_vectorizer, "data cable ESP32 Arduino embedded"),
        })

    # --- Wired networking reliability ---
    if req.get("wired_networking") and laptop.get("ethernet_port") == 0:
        recs.append({
            "key": "ethernet_adapter", "tier": "Optional",
            "reason": "No built-in Ethernet port, but you need reliable wired networking sometimes.",
            "evidence": _kb_reason(kb_collection, kb_vectorizer, "Ethernet adapter wired networking reliability"),
        })

    # --- Sustained gaming/workstation load -> cooling pad ---
    if "gaming" in workloads and (laptop.get("weight_kg") or 9) < 2.0:
        # Lighter gaming chassis usually means less cooling headroom than a bulkier gaming laptop.
        recs.append({
            "key": "cooling_pad", "tier": "Optional",
            "reason": "A slim gaming chassis has less cooling headroom for long sustained sessions.",
            "evidence": _kb_reason(kb_collection, kb_vectorizer, "cooling pad sustained gaming thermal throttling"),
        })

    return recs


def hidden_cost_breakdown(laptop, accessories):
    """Totals use observed price, else MSRP; if neither is known, laptop price stays None (never 0)."""
    price = laptop.get("observed_price_inr") or laptop.get("msrp_inr")
    tot = lambda tier: sum(ACCESSORY_CATALOG[a["key"]]["price_inr"] for a in accessories
                           if a["tier"] == tier and a["key"])
    e, r, o = tot("Essential"), tot("Recommended"), tot("Optional")
    base = price or 0
    return {
        "laptop_price": price, "essential_accessories": e, "recommended_accessories": r,
        "optional_accessories": o,
        "must_spend_total": base + e if price else None,
        "fully_equipped_total": base + e + r + o if price else None,
    }


def print_accessory_report(laptop, req, kb_collection, kb_vectorizer):
    print(f"\n{laptop['brand']} {laptop['model_name']} — ₹{laptop['msrp_inr']:,.0f}")
    print(f"  Box contents: {laptop['box_contents']}")
    accessories = recommend_accessories(laptop, req, kb_collection, kb_vectorizer)
    if not accessories:
        print("  No additional accessories flagged for this profile.")
    for a in accessories:
        if a["tier"] == "Limitation":
            print(f"  ⚠ LIMITATION — {a['reason']} [{a['evidence']}]")
            continue
        item = ACCESSORY_CATALOG[a["key"]]
        print(f"  [{a['tier']}] {item['name']} (~₹{item['price_inr']:,}) — {a['reason']} [{a['evidence']}]")

    costed = [a for a in accessories if a["tier"] != "Limitation"]
    costs = hidden_cost_breakdown(laptop, costed)
    print(f"  --- Hidden-cost calculation ---")
    print(f"  Laptop price:              ₹{costs['laptop_price']:,.0f}")
    print(f"  + Essential accessories:   ₹{costs['essential_accessories']:,}")
    print(f"  = Must-spend total:        ₹{costs['must_spend_total']:,.0f}")
    print(f"  + Recommended + Optional:  ₹{costs['recommended_accessories'] + costs['optional_accessories']:,}")
    print(f"  = Fully-equipped total:    ₹{costs['fully_equipped_total']:,.0f}")


if __name__ == "__main__":
    laptops = load_laptops()
    kb_collection, kb_vectorizer = load_kb()

    print("=" * 78)
    print("PROFILE A — CAD/engineering student, desk-based, wants digital notes")
    print("=" * 78)
    req_a = {
        "budget_max": 220000,
        "ram_min_gb": 16,
        "required_workloads": ["cad_engineering"],
        "desk_based": True,
        "digital_notes": True,
        "many_peripherals": True,
    }
    passed, _ = hard_filter(laptops, req_a)
    top = rerank_diverse(score_candidates(passed, req_a), top_n=2)
    for c in top:
        print_accessory_report(c, req_a, kb_collection, kb_vectorizer)

    print("\n" + "=" * 78)
    print("PROFILE B — ML/DL student with an ESP32 hobby project, needs wired networking")
    print("=" * 78)
    req_b = {
        "budget_max": 150000,
        "ram_min_gb": 16,
        "required_workloads": ["ml_dl"],
        "embedded_dev": True,
        "wired_networking": True,
        "dataset_size_gb": 900,
    }
    passed, _ = hard_filter(laptops, req_b)
    top = rerank_diverse(score_candidates(passed, req_b), top_n=2)
    for c in top:
        print_accessory_report(c, req_b, kb_collection, kb_vectorizer)

    print("\n" + "=" * 78)
    print("PROFILE C — Gamer, no extra needs (should show minimal/no accessories)")
    print("=" * 78)
    req_c = {"budget_max": 150000, "required_workloads": ["gaming"]}
    passed, _ = hard_filter(laptops, req_c)
    top = rerank_diverse(score_candidates(passed, req_c), top_n=2)
    for c in top:
        print_accessory_report(c, req_c, kb_collection, kb_vectorizer)
