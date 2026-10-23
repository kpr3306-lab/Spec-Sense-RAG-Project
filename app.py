"""SpecSense frontend.  Run:  streamlit run app.py   (set SPECSENSE_EDIT=1 to allow price editing)"""
import os
import pandas as pd
import streamlit as st
import api
import html
from pathlib import Path
import scores
import recommendation_engine as R

st.set_page_config(page_title="SpecSense", page_icon=":material/laptop_mac:", layout="wide")

@st.cache_resource
def kb_resources():
    try:
        return R.load_kb()
    except Exception:  # knowledge base not built here (or chromadb missing): recommendations still work, no evidence
        return None, None

def laptops():  # not cached: price edits must show immediately
    return R.load_laptops()

L = laptops()
kb, vec = kb_resources()
EDITABLE = os.environ.get("SPECSENSE_EDIT") == "1"  # off when deployed: the cloud disk resets and anyone with the URL could edit
unk = lambda v, suf="": "unknown" if v is None or v == "" or (isinstance(v, float) and pd.isna(v)) else f"{v:g}{suf}" if isinstance(v, (int, float)) else f"{v}{suf}"
known = lambda *parts, sep=" ": sep.join(p for p in parts if p != "unknown") or "unknown"  # '16" unknown unknown' -> '16"'
inr = lambda v: "price unknown" if not v else f"₹{v:,.0f}"
stars = lambda l: f"★ {l['rating']:g} ({l.get('rating_count') or 0:,.0f} ratings)" if l.get("rating") else "No rating available"
WORKLOADS = {"coding_dev": "Coding / dev", "student_general": "Student / general", "content_creation": "Content creation",
             "gaming": "Gaming", "ml_dl": "ML / deep learning", "cad_engineering": "CAD / engineering",
             "business_thin_light": "Business / thin & light", "budget": "Budget"}
DIMS = {"performance": "Performance", "display": "Display", "portability": "Portability",
        "connectivity": "Ports", "upgradeability": "Upgradeability", "service": "Service", "brand_colour": "Brand/colour"}

SPEC_INFO = {
    "cpu": {
        "purpose": "The CPU runs the operating system, applications, and general-purpose calculations. "
                   "More cores and threads help with parallel work such as compiling and multitasking; "
                   "single-core speed matters more for lightly threaded tasks.",
        "fields": [
            ("Cores", "cpu_cores", ""),
            ("Threads", "cpu_threads", ""),
            ("Performance cores", "cpu_p_cores", ""),
            ("Efficiency cores", "cpu_e_cores", ""),
            ("Base clock", "cpu_base_clock_ghz", " GHz"),
            ("Boost clock", "cpu_boost_clock_ghz", " GHz"),
            ("Architecture", "cpu_architecture", ""),
            ("Cache", "cpu_cache_mb", " MB"),
            ("Processor power (TDP)", "cpu_tdp_w", " W"),
            ("AI accelerator (NPU TOPS)", "npu_tops", " TOPS"),
        ],
    },
    "gpu": {
        "purpose": "The GPU draws graphics and accelerates parallel workloads such as games, 3D rendering, "
                   "video effects, and some machine-learning tasks. A discrete GPU and more VRAM can help "
                   "heavy graphics workloads, while configured power (TGP) affects sustained performance.",
        "fields": [
            ("GPU type", "gpu_type", ""),
            ("Architecture", "gpu_architecture", ""),
            ("Dedicated memory (VRAM)", "gpu_vram_gb", " GB"),
            ("VRAM type", "gpu_vram_type", ""),
            ("Memory bus", "gpu_memory_bus_bit", " bit"),
            ("Graphics power (TGP)", "gpu_tgp_w", " W"),
            ("MUX switch", "gpu_mux_switch", ""),
            ("Advanced Optimus", "gpu_advanced_optimus", ""),
        ],
        "note": "GPU TOPS are not listed in this catalogue. NPU TOPS, shown in the CPU details when available, "
                "measure a separate AI accelerator and are not a GPU performance score.",
    },
    "ram": {
        "purpose": "RAM holds data for applications that are currently running. More capacity helps with "
                   "large projects, many browser tabs, and virtual machines. Soldered memory and available "
                   "slots determine whether you can upgrade it later.",
        "fields": [
            ("Capacity", "ram_gb", " GB"),
            ("Memory type", "ram_type", ""),
            ("Speed", "ram_speed_mhz", " MT/s"),
            ("Upgradeable", "ram_upgradeable", ""),
            ("Maximum capacity", "ram_max_gb", " GB"),
            ("Memory slots", "ram_slots", ""),
            ("Soldered capacity", "ram_soldered_gb", " GB"),
        ],
    },
    "storage": {
        "purpose": "Storage holds the operating system, applications, and files. Capacity determines how much "
                   "fits; interface and drive type affect transfer speeds. Extra slots can allow a second SSD "
                   "to be added without replacing the original.",
        "fields": [
            ("Capacity", "storage_gb", " GB"),
            ("Drive type", "storage_type", ""),
            ("Interface", "storage_interface", ""),
            ("M.2/storage slots", "storage_slots", ""),
            ("Upgradeable", "storage_upgradeable", ""),
        ],
    },
    "display": {
        "purpose": "The display affects reading comfort, workspace, smoothness, and colour work. Higher "
                   "resolution and refresh rate can look sharper and smoother but may use more battery; "
                   "brightness and colour coverage matter for bright rooms and creative work.",
        "fields": [
            ("Size", "display_size_in", " in"),
            ("Resolution", "display_resolution", ""),
            ("Aspect ratio", "display_aspect_ratio", ""),
            ("Panel type", "display_panel_type", ""),
            ("Refresh rate", "display_refresh_hz", " Hz"),
            ("Brightness", "display_brightness_nits", " nits"),
            ("Colour gamut", "display_color_gamut", ""),
            ("Colour depth", "display_color_depth", ""),
            ("Response time", "display_response_ms", " ms"),
            ("HDR", "display_hdr", ""),
            ("Variable refresh rate", "display_vrr", ""),
            ("Touchscreen", "touch_screen", ""),
        ],
    },
    "weight": {
        "purpose": "Weight affects how comfortable the laptop is to carry every day. Compare the laptop itself "
                   "and remember that the charger and accessories add to your bag weight.",
        "fields": [
            ("Width", "dimensions_width_mm", " mm"),
            ("Depth", "dimensions_depth_mm", " mm"),
            ("Thickness", "dimensions_thickness_mm", " mm"),
            ("Build material", "build_material", ""),
        ],
    },
    "ports": {
        "purpose": "Ports determine which accessories, displays, storage devices, and networks can connect "
                   "without adapters. USB-C features vary by laptop, so check display output, charging, and "
                   "Thunderbolt/USB4 support rather than relying on the connector shape alone.",
        "fields": [
            ("USB-A count / speed", "usb_a_count", ""),
            ("USB-A speed", "usb_a_speed", ""),
            ("USB-C count / speed", "usb_c_count", ""),
            ("USB-C speed", "usb_c_speed", ""),
            ("Thunderbolt / USB4", "thunderbolt_usb4", ""),
            ("USB-C display output", "usb_c_display_output", ""),
            ("HDMI version", "hdmi_version", ""),
            ("SD card reader", "sd_card_reader", ""),
            ("Ethernet", "ethernet_port", ""),
            ("Wi-Fi", "wifi_gen", ""),
            ("Bluetooth", "bluetooth_version", ""),
        ],
    },
    "warranty": {
        "purpose": "Warranty coverage affects repair cost and downtime if something goes wrong. Duration, "
                   "onsite service, accidental-damage coverage, and service availability can differ by exact SKU.",
        "fields": [
            ("Duration", "warranty_years", " yr"),
            ("Coverage type", "warranty_type", ""),
            ("Onsite support", "onsite_support", ""),
            ("Accidental-damage option", "accidental_damage_option", ""),
            ("Service network", "service_network_coverage", ""),
            ("Spare-part availability", "spare_part_availability", ""),
        ],
    },
}


st.markdown("""
<style>
.block-container{padding-top:2.2rem;max-width:1240px}
.ss-hero{padding:1.1rem 1.4rem;border-radius:16px;margin-bottom:.6rem;
  background:linear-gradient(120deg,rgba(56,189,248,.16),rgba(99,102,241,.14) 55%,rgba(168,85,247,.10));
  border:1px solid rgba(125,140,170,.25)}
.ss-hero h1{margin:0;font-size:2rem;font-weight:750;letter-spacing:-.02em;padding:0}
.ss-hero p{margin:.25rem 0 0;opacity:.75;font-size:.95rem}
.ss-title{font-size:1.35rem;font-weight:700;letter-spacing:-.01em;line-height:1.25}
.ss-rank{display:inline-block;min-width:2rem;text-align:center;padding:.05rem .5rem;margin-right:.55rem;border-radius:999px;
  background:rgba(56,189,248,.18);color:#38bdf8;font-weight:700;font-size:.95rem}
.ss-sub{opacity:.65;font-size:.85rem;margin-top:.25rem}
.ss-chip{display:inline-block;padding:.12rem .6rem;margin:.3rem .35rem 0 0;border-radius:999px;font-size:.78rem;
  border:1px solid rgba(125,140,170,.35);opacity:.9}
.ss-score{text-align:right}
.ss-score .num{font-size:2.3rem;font-weight:780;line-height:1;letter-spacing:-.02em}
.ss-score .lab{font-size:.72rem;text-transform:uppercase;letter-spacing:.08em;opacity:.6}
.ss-score .cov{font-size:.72rem;opacity:.55;margin-top:.2rem}
.ss-good{color:#34d399}.ss-ok{color:#fbbf24}.ss-low{color:#f87171}
.ss-bar{display:flex;align-items:center;gap:.7rem;margin:.28rem 0;font-size:.85rem}
.ss-bar .n{width:7.5rem;opacity:.8}.ss-bar .t{flex:1;height:8px;border-radius:99px;background:rgba(125,140,170,.18);overflow:hidden}
.ss-bar .f{height:100%;border-radius:99px;background:linear-gradient(90deg,#38bdf8,#818cf8)}
.ss-bar .v{width:2.6rem;text-align:right;font-variant-numeric:tabular-nums;opacity:.75}
.ss-sec{font-size:.72rem;text-transform:uppercase;letter-spacing:.09em;opacity:.55;margin:1rem 0 .3rem;font-weight:650}
.ss-pill{display:flex;justify-content:space-between;align-items:center;padding:.5rem .8rem;border-radius:12px;
  background:rgba(125,140,170,.10);border:1px solid rgba(125,140,170,.18);margin:.2rem 0;font-size:.86rem}
.ss-tier{font-size:.68rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;padding:.1rem .5rem;border-radius:99px;margin-right:.6rem}
.ss-Essential{background:rgba(248,113,113,.18);color:#f87171}.ss-Recommended{background:rgba(251,191,36,.18);color:#fbbf24}
.ss-Optional{background:rgba(125,140,170,.2);opacity:.85}
.ss-why{padding:.65rem .9rem;border-radius:12px;border-left:3px solid #fbbf24;background:rgba(251,191,36,.08);font-size:.88rem;margin:.6rem 0}
/* spec rows + clean (i) info buttons */
[class*="st-key-spec-info-"] button{width:26px!important;height:26px!important;min-height:26px!important;padding:0!important;
  border-radius:50%!important;border:none!important;background:transparent!important;color:rgba(150,165,190,.85)!important;box-shadow:none!important;
  transition:background .15s,color .15s}
[class*="st-key-spec-info-"] button:hover,[class*="st-key-spec-info-"] button[aria-expanded="true"]{background:rgba(56,189,248,.16)!important;color:#38bdf8!important}
[class*="st-key-spec-info-"] button span[aria-hidden="true"]{display:none!important}
[class*="st-key-spec-info-"] button div{margin:0!important;gap:0!important}
[class*="st-key-spec-info-"] button p{display:none!important}
[class*="st-key-spec-info-"] button span[data-testid="stIconMaterial"]{font-size:20px!important;display:inline-block!important}
.ss-spec{padding:.18rem 0;font-size:.92rem;border-bottom:1px dashed rgba(125,140,170,.18)}
.ss-spec b{display:inline-block;min-width:5.4rem;opacity:.6;font-weight:600;font-size:.78rem;text-transform:uppercase;letter-spacing:.05em}
[data-testid="stMetric"]{background:rgba(125,140,170,.08);border:1px solid rgba(125,140,170,.16);padding:.55rem .8rem;border-radius:12px}
[data-testid="stMetricLabel"]{opacity:.7}
div[data-baseweb="tab-list"]{gap:.4rem}
</style>
""", unsafe_allow_html=True)


_SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="{s}" height="{s}" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-0.18em">{p}</svg>'
_PATHS = {
    "laptop": '<rect x="4.5" y="5" width="15" height="10" rx="1.6"/><path d="M2.5 18.5h19M9.5 18.5l.6-1.2h3.8l.6 1.2"/>',
    "palette": '<path d="M12 3.5a8.5 8.5 0 1 0 0 17c1.2 0 1.7-.8 1.4-1.7-.4-1.1.2-2.1 1.4-2.1H17a3.5 3.5 0 0 0 3.5-3.5C20.5 7.2 16.7 3.5 12 3.5z"/><circle cx="8" cy="11" r=".9"/><circle cx="11" cy="7.8" r=".9"/><circle cx="15" cy="8.6" r=".9"/>',
    "tag": '<path d="M3.5 12.2V4.5a1 1 0 0 1 1-1h7.7a1 1 0 0 1 .7.3l7.3 7.3a1 1 0 0 1 0 1.4l-7.4 7.4a1 1 0 0 1-1.4 0L3.8 12.9a1 1 0 0 1-.3-.7z"/><circle cx="8" cy="8" r="1.2"/>',
    "shield": '<path d="M12 3l7.5 2.8v5.6c0 4.6-3.1 8-7.5 9.6-4.4-1.6-7.5-5-7.5-9.6V5.8L12 3z"/><path d="M8.7 12.2l2.2 2.2 4.4-4.6"/>',
    "image": '<rect x="3.5" y="4.5" width="17" height="15" rx="2"/><circle cx="9" cy="10" r="1.6"/><path d="M4 17l5-4.5 3.5 3L15 13l5 4.5"/>',
}
def icon(name, size=15): return _SVG.format(s=size, p=_PATHS[name])
def laptop_placeholder():
    return ('<div style="display:flex;align-items:center;justify-content:center;height:112px;border-radius:14px;color:rgba(150,165,190,.7);'
            'background:linear-gradient(135deg,rgba(56,189,248,.08),rgba(129,140,248,.08));border:1px dashed rgba(125,140,170,.3)">'
            + icon("laptop", 64) + '</div>')

def tone(v): return "ss-good" if v >= 75 else "ss-ok" if v >= 55 else "ss-low"
def bars_html(dims):
    out = []
    for k, label in DIMS.items():
        v = dims.get(k)
        if v is not None:
            out.append(f'<div class="ss-bar"><span class="n">{label}</span><span class="t"><span class="f" style="display:block;width:{v*100:.0f}%"></span></span><span class="v">{v*100:.0f}</span></div>')
    return "".join(out)

def render_spec(container, laptop, card_index, key, label, value):
    if value == "unknown": return
    text_col, info_col = container.columns([14, 1], vertical_alignment="center", gap="small")
    text_col.markdown(f'<div class="ss-spec"><b>{html.escape(label)}</b> {html.escape(str(value))}</div>', unsafe_allow_html=True)
    info = SPEC_INFO[key]
    with info_col.popover(" ", icon=":material/info:", help=f"{label}: details & why it matters",
                          key=f"spec-info-{card_index}-{key}"):
        st.markdown(f"#### {label}")
        st.markdown(f"**Shown:** {value}")
        st.markdown(f"**Why it matters:** {info['purpose']}")
        details = [(detail_label, unk(laptop.get(field), suffix)) for detail_label, field, suffix in info["fields"]]
        details = [(detail_label, v) for detail_label, v in details if v != "unknown"]
        if details:
            st.markdown("**Detailed specifications**")
            for detail_label, v in details:
                st.markdown(f"- **{detail_label}:** {v}")
        if "note" in info:
            st.caption(info["note"])

priced = sum(1 for l in L if l["observed_price_inr"] or l["msrp_inr"])
checked = max((l["price_last_checked_date"] for l in L if l.get("price_last_checked_date")), default=None)
st.markdown('<div class="ss-hero"><h1><span style="color:#38bdf8">'+icon("laptop",30)+'</span> SpecSense</h1><p>Describe what you do — not processor names. Every number comes from the catalogue; unknown stays unknown.</p>'
            f'<span class="ss-chip">{icon("laptop",13)} {len(L)} laptops</span><span class="ss-chip">{icon("tag",13)} {priced} with a current price'
            + (f' · checked {checked}' if checked else '') + f'</span><span class="ss-chip">★ {sum(1 for l in L if l.get("rating"))} rated</span>'
            + ('' if kb is not None else '<span class="ss-chip">knowledge base not built — no evidence snippets</span>') + '</div>', unsafe_allow_html=True)
if priced == 0:
    st.warning("No laptop in the catalogue has a price yet, so the **budget filter can't exclude anything**. "
               "Add prices with the importers, or in the *Catalogue & prices* tab when running locally with SPECSENSE_EDIT=1.")

tab_find, tab_search, tab_cmp, tab_cat, tab_learn = st.tabs([":material/search: Find my laptop", ":material/manage_search: Model search", ":material/compare_arrows: Compare", ":material/table_chart: Catalogue & prices", ":material/menu_book: Learn"])

# ---------------------------------------------------------------- Find
with tab_find:
    with st.form("req"):
        c1, c2, c3 = st.columns(3)
        req_w = c1.multiselect("Main use (must suit)", list(WORKLOADS), format_func=WORKLOADS.get, default=["coding_dev"])
        soft_w = c1.multiselect("Also nice to suit", list(WORKLOADS), format_func=WORKLOADS.get)
        budget = c2.number_input("Max budget ₹ (0 = no limit)", 0, 1000000, 0, 5000)
        weight = c2.number_input("Max weight kg (0 = no limit)", 0.0, 4.0, 0.0, 0.1)
        ram = c2.selectbox("Minimum RAM (GB)", [0, 8, 16, 32], index=2)
        usb_a = c3.checkbox("Must have USB-A")
        brands = c3.multiselect("Preferred brands", sorted({l["brand"] for l in L if l["brand"]}))
        colours = c3.multiselect("Preferred colours", sorted({l["colour"] for l in L if l["colour"]}))
        with st.expander("Accessory needs & scoring weights"):
            a1, a2, a3 = st.columns(3)
            desk = a1.checkbox("Desk-based work"); notes = a1.checkbox("Digital note-taking")
            periph = a2.checkbox("Many peripherals"); embedded = a2.checkbox("ESP32/Arduino dev")
            wired = a3.checkbox("Need wired networking")
            wts = {k: st.slider(v, 0, 10, int(R.DEFAULT_WEIGHTS.get(k, .05) * 100 / 5)) for k, v in DIMS.items()}
        go = st.form_submit_button("Recommend", type="primary")
    if go:
        req = {"required_workloads": req_w, "soft_workloads": [w for w in soft_w if w not in req_w],
               "preferred_brands": brands, "preferred_colours": colours, "usb_a_required": usb_a,
               "desk_based": desk, "digital_notes": notes, "many_peripherals": periph,
               "embedded_dev": embedded, "wired_networking": wired}
        if budget: req["budget_max"] = budget
        if weight: req["weight_max_kg"] = weight
        if ram: req["ram_min_gb"] = ram
        tot = sum(wts.values()) or 1
        res = api.run(L, req, kb, vec, weights={k: v / tot for k, v in wts.items()})
        st.session_state["res"] = res

    res = st.session_state.get("res")
    if res:
        st.subheader(f"{res['passed']} of {res['total']} laptops meet every hard requirement")
        if not res["candidates"]:
            st.error("No exact match.")
            if res["compromises"]:
                st.write("Nearest compromises:")
                for d, n in res["compromises"]: st.write(f"• If you **{d}** → {n} laptop(s) become available")
            else:
                st.write("No single relaxation unlocks a match — the requirements conflict more fundamentally.")
            with st.expander("Why each laptop was rejected"):
                for r in res["rejected"]: st.write(f"**{r['model_name']}** — " + "; ".join(r["reasons"]))
        for i, c in enumerate(res["candidates"], 1):
            with st.container(border=True):
                h0, h1, h2 = st.columns([1.5, 4, 1.3], vertical_alignment="center")
                img = None
                if c.get("image_path") and Path(R.BASE_DIR, c["image_path"]).exists(): img = str(Path(R.BASE_DIR, c["image_path"]))
                elif c.get("image_primary_url"): img = c["image_primary_url"]
                if img:
                    h0.image(img, width="stretch")
                    if c.get("image_source_url") or c.get("image_source"):
                        h0.caption(f"Image: {c.get('image_source_url') or c.get('image_source')}")
                else:
                    h0.markdown(laptop_placeholder(), unsafe_allow_html=True)
                price = c['observed_price_inr'] or c['msrp_inr']
                pdate = f" · {c['price_last_checked_date']}" if c.get("observed_price_inr") and c.get("price_last_checked_date") else ""
                buy = c.get("price_source_url")
                h1.markdown(f'<div class="ss-title"><span class="ss-rank">#{i}</span>{html.escape(c["brand"] or "")} {html.escape(c["model_name"])}</div>'
                            f'<div class="ss-sub">SKU {html.escape(str(c["sku_id"]))}</div>'
                            + (f'<span class="ss-chip">{icon("palette",13)} {html.escape(c["colour"])}</span>' if c.get("colour") else "")
                            + f'<span class="ss-chip">{icon("tag",13)} {inr(price)}{html.escape(pdate)}</span>'
                            f'<span class="ss-chip">{html.escape(stars(c))}</span>'
                            + (f'<span class="ss-chip">{icon("shield",13)} confidence {html.escape(str(c["confidence"]))}</span>' if c.get("confidence") else "")
                            + (f'<a class="ss-chip" href="{html.escape(buy)}" target="_blank">View on {html.escape(c.get("retailer_name") or "store")} ↗</a>' if buy else ""),
                            unsafe_allow_html=True)
                if c.get("price_note"): h1.caption("Price note: " + c["price_note"])
                h2.markdown(f'<div class="ss-score"><div class="lab">Fit score</div><div class="num {tone(c["fit_score"])}">{c["fit_score"]:.0f}<span style="font-size:1rem;opacity:.5">/100</span></div>'
                            f'<div class="cov">{c["score_coverage"]:.0%} of dimensions known</div></div>', unsafe_allow_html=True)
                s1, s2, s3 = st.columns(3)
                render_spec(s1, c, i, "cpu", "CPU", unk(c["cpu_model"]))
                render_spec(s1, c, i, "gpu", "GPU", unk(c["gpu_model"]))
                render_spec(s1, c, i, "ram", "RAM", known(unk(c['ram_gb'], ' GB'), unk(c['ram_type'])))
                render_spec(s2, c, i, "storage", "Storage", known(unk(c['storage_gb'], ' GB'), unk(c['storage_type'])))
                render_spec(s2, c, i, "display", "Display", known(unk(c['display_size_in'], '"'),
                            unk(c['display_resolution']), unk(c['display_panel_type'])))
                render_spec(s2, c, i, "weight", "Weight", unk(c["weight_kg"], " kg"))
                render_spec(s3, c, i, "ports", "Ports",
                            known(unk(c['usb_a_count'], '× USB-A'), unk(c['usb_c_count'], '× USB-C'), sep=" · "))
                render_spec(s3, c, i, "warranty", "Warranty", unk(c["warranty_years"], " yr"))
                st.markdown('<div class="ss-sec">How it fits you</div>' + bars_html(c["dims"]), unsafe_allow_html=True)
                ps = {k: v for k, v in scores.all_scores(c).items() if v[0] is not None}
                if ps:
                    st.markdown('<div class="ss-sec">Persona scores</div>', unsafe_allow_html=True)
                    for col, (name, (val, cov)) in zip(st.columns(len(ps)), ps.items()):
                        col.metric(name, f"{val}/100", help=f"{cov:.0%} of inputs known")
                if c["weakest"]:
                    st.markdown(f'<div class="ss-why"><b>Why not?</b> Your biggest compromise is <b>{DIMS[c["weakest"]]}</b>.</div>', unsafe_allow_html=True)
                if c["accessories"]:
                    st.markdown('<div class="ss-sec">Accessories</div>', unsafe_allow_html=True)
                    for a in c["accessories"]:
                        pr = f"~₹{a['price_inr']:,}" if a.get("price_inr") else ""
                        st.markdown(f'<div class="ss-pill"><span><span class="ss-tier ss-{a["tier"]}">{a["tier"]}</span><b>{html.escape(a["key"].replace("_"," ").title())}</b> — {html.escape(a["reason"])}</span><span style="opacity:.7;white-space:nowrap">{pr}</span></div>', unsafe_allow_html=True)
                    cost = c["cost"]
                    st.caption("Total setup: " + (f"₹{cost['must_spend_total']:,.0f} must-have · ₹{cost['fully_equipped_total']:,.0f} fully equipped" if cost["must_spend_total"] else f"laptop price unknown — accessories alone: ₹{cost['essential_accessories']:,} essential"))
                with st.expander("Evidence & sources"):
                    for e in c["evidence"]: st.markdown(f"**[{e['doc_id']}] {e['section']}** — {e['text'][:400]}…")
                    st.write(f"Source: {unk(c['source_url'])} · verified {unk(c['last_verified_date'])}" + (f" · confidence {c['confidence']}" if c.get("confidence") else ""))
        if res["tradeoffs"]:
            st.markdown("#### Trade-offs between your top two")
            for t in res["tradeoffs"]: st.write("• " + t)
        s = res["smart"]
        if s:
            st.success(f"**Smart pick (ignores budget):** {s['brand'] or ''} {s['model_name']} — workload fit {s['workload_perf_score']}/100, {inr(s['observed_price_inr'] or s['msrp_inr'])}"
                       + (f". That is {s['over_budget_pct']:.0f}% over your budget." if s["over_budget_pct"] else ""))

# ---------------------------------------------------------------- Model search
with tab_search:
    q = st.text_input("Search a model or SKU", placeholder="e.g. Victus, MacBook Air M5, IdeaPad Slim 3, 15-fd0262TU, COMHGWQESQN4BAHV")
    if q:
        groups = api.variants(L, q)
        if not groups:
            st.info("No laptop matches all of those words. Try fewer words, or just the series name.")
        else:
            st.caption(f"{sum(len(v) for _, v in groups)} variants of {len(groups)} model(s), cheapest first. "
                       "Prices are current selling prices (not MRP).")
        for name, vs in groups:
            known = [v["observed_price_inr"] for v in vs if v.get("observed_price_inr")]
            span = f"{inr(min(known))} – {inr(max(known))}" if known else "price unknown"
            with st.expander(f"**{name}** · {len(vs)} variant(s) · {span}", expanded=len(groups) <= 3):
                st.dataframe(pd.DataFrame([{
                    "Variant": v["model_name"], "CPU": unk(v["cpu_model"]), "RAM": unk(v["ram_gb"], " GB"),
                    "Storage": f"{unk(v['storage_gb'], ' GB')} {v['storage_type'] or ''}".strip(), "GPU": unk(v["gpu_model"]),
                    "Display": unk(v["display_size_in"], '"'), "OS": unk(v["os"]), "Price ₹": v["observed_price_inr"] or v["msrp_inr"],
                    "Rating": stars(v), "SKU": v["sku_id"], "Link": v.get("price_source_url") or v.get("source_url"),
                } for v in vs]), hide_index=True, width="stretch",
                    column_config={"Price ₹": st.column_config.NumberColumn(format="₹%d"),
                                   "Link": st.column_config.LinkColumn(display_text="Open ↗")})

# ---------------------------------------------------------------- Compare
with tab_cmp:
    names = {f"{l['brand'] or ''} {l['model_name']} [{l['sku_id']}]".strip(): l for l in L}
    pick = st.multiselect("Pick 2–3 exact SKUs", list(names), max_selections=3)
    if len(pick) >= 2:
        rows = [("Price", "observed_price_inr", None), ("Rating", "rating", 1), ("CPU", "cpu_model", None), ("GPU VRAM (GB)", "gpu_vram_gb", 1),
                ("RAM (GB)", "ram_gb", 1), ("Storage (GB)", "storage_gb", 1), ("Display refresh (Hz)", "display_refresh_hz", 1),
                ("Brightness (nits)", "display_brightness_nits", 1), ("Weight (kg)", "weight_kg", -1), ("Battery (Wh)", "battery_wh", 1),
                ("USB-A ports", "usb_a_count", 1), ("USB-C ports", "usb_c_count", 1), ("Warranty (yr)", "warranty_years", 1)]
        data = {}
        for label, col, direction in rows:
            vals = [names[p].get(col) for p in pick]
            if all(unk(v) == "unknown" for v in vals): continue
            cells = [stars(names[p]) if col == "rating" else unk(v) for v, p in zip(vals, pick)]
            nums = [v for v in vals if isinstance(v, (int, float)) and not pd.isna(v)]
            if direction and len(nums) == len(vals) and len(set(nums)) > 1:  # only crown a winner when ALL are known
                best = max(nums) if direction == 1 else min(nums)
                cells = [c + " · best" if v == best else c for c, v in zip(cells, vals)]
            data[label] = cells
        st.table(pd.DataFrame(data, index=[n.split(" [")[0] for n in pick]).T)
        st.caption("Unsure what a row means? Look it up in the **Learn** tab (e.g. TGP, PPI, soldered RAM).")
        st.caption("“best” marks a winner only when every compared laptop has a known value; unknown is never treated as zero.")

# ---------------------------------------------------------------- Catalogue
with tab_cat:
    df = pd.DataFrame(L)
    df["rating_text"] = [stars(l) for l in L]
    show = df[["sku_id", "brand", "model_name", "colour", "ram_gb", "weight_kg", "gpu_model", "observed_price_inr", "rating_text", "last_verified_date"]]
    st.dataframe(show, width='stretch', hide_index=True, column_config={"observed_price_inr": st.column_config.NumberColumn("Current price ₹", format="₹%d"), "rating_text": "Rating"})
    if EDITABLE:
        st.markdown("#### Prices")
        st.caption("Edit directly (price, retailer, product URL, date seen). A price is only saved with a URL and a date, so every number stays traceable.")
        ed = pd.DataFrame(L)[["sku_id", "model_name", "observed_price_inr", "retailer_name", "price_source_url", "price_last_checked_date"]]
        edited = st.data_editor(ed, hide_index=True, width="stretch", disabled=["sku_id", "model_name"], key="price_editor",
                                column_config={"observed_price_inr": st.column_config.NumberColumn("Price ₹", min_value=15000, max_value=600000, step=500, format="%d"),
                                               "retailer_name": "Retailer", "price_source_url": st.column_config.LinkColumn("Product URL"),
                                               "price_last_checked_date": "Date seen (YYYY-MM-DD)"})
        if st.button("Save price changes", type="primary"):
            changed, errors = 0, []
            for (_, a_), (_, b_) in zip(ed.iterrows(), edited.iterrows()):
                if a_.fillna("").tolist() == b_.fillna("").tolist(): continue
                if pd.isna(b_["observed_price_inr"]): continue
                if not str(b_["price_source_url"] or "").startswith("http") or not str(b_["price_last_checked_date"] or "")[:4].isdigit():
                    errors.append(f"{b_['sku_id']}: needs a product URL and a date"); continue
                api.save_price(b_["sku_id"], float(b_["observed_price_inr"]), b_["retailer_name"], b_["price_source_url"], str(b_["price_last_checked_date"]))
                changed += 1
            for e in errors: st.error(e)
            if changed: st.success(f"Saved {changed} price(s)."); st.rerun()
        st.caption("Only the live-price columns are touched; verified spec fields are never overwritten.")

# ---------------------------------------------------------------- Learn
with tab_learn:
    q = st.text_input("Ask about a term (e.g. TGP, NPU TOPS, soldered RAM, PPI)")
    if kb is None:
        st.info("The knowledge base isn't built on this machine yet (knowledge_base/ → `python ingest_kb.py`), so there is nothing to look up.")
    elif q:
        for e in R.kb_query(kb, vec, q, k=3):
            st.markdown(f"**[{e['doc_id']}] {e['section']}**\n\n{e['text']}")
