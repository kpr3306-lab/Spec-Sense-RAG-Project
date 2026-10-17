"""Roadmap persona scores. Each signal is 0-1 or None (unknown); unknown signals are skipped, never zero.
Returns (score_0_100 | None, coverage 0-1). Needs >= 50% signal coverage to report a score."""
from recommendation_engine import _num

def _lin(v, lo, hi, invert=False):
    v = _num(v)
    if v is None: return None
    x = min(1, max(0, (v - lo) / (hi - lo)))
    return 1 - x if invert else x

def _has(v):
    return None if v is None or v == "" else 1.0

def _flag(v):
    v = _num(v)
    return None if v is None else (1.0 if v > 0 else 0.0)

def _combine(signals):
    known = [s for s in signals if s is not None]
    cov = len(known) / len(signals)
    return (round(sum(known) / len(known) * 100), cov) if known and cov >= 0.5 else (None, cov)

def _gamut(g):
    g = (g or "").lower()
    if not g: return None
    return 1.0 if any(k in g for k in ("p3", "adobe", "dci")) else 0.6 if "srgb" in g else 0.3

def _ram_layout(l):
    lay = (l.get("ram_layout") or "").lower()
    if lay: return 1.0 if ("so-dimm" in lay or "lpcamm" in lay) else 0.5 if "mixed" in lay else 0.0
    return _flag(l.get("ram_upgradeable"))

def travel(l):
    return _combine([_lin(l.get("weight_kg"), 1.1, 2.3, True), _lin(l.get("battery_wh"), 40, 75),
                     _flag(l.get("usb_c_charging")), _lin(l.get("charger_watt"), 45, 150, True)])

def college(l):
    return _combine([_lin(l.get("weight_kg"), 1.2, 2.3, True), _lin(l.get("battery_wh"), 40, 75),
                     _has(l.get("webcam_resolution")), _flag(l.get("usb_a_count")), _lin(l.get("warranty_years"), 1, 3)])

def developer(l):
    return _combine([_lin(l.get("ram_gb"), 8, 32), _lin(l.get("cpu_threads"), 4, 20), _ram_layout(l),
                     _lin(l.get("storage_gb"), 256, 1024), _flag(l.get("usb_a_count"))])

def creator(l):
    oled = (l.get("display_panel_type") or "")
    return _combine([_gamut(l.get("display_color_gamut")), (1.0 if "oled" in oled.lower() else 0.5) if oled else None,
                     _lin(l.get("gpu_vram_gb") if l.get("gpu_type") == "Discrete" else 0, 0, 8),
                     _lin(l.get("ram_gb"), 8, 32), _flag(l.get("sd_card_reader"))])

def upgrade_path(l):
    free = _num(l.get("storage_free_slots")); slots = _num(l.get("storage_slots"))
    stor = (1.0 if free > 0 else 0.0) if free is not None else (1.0 if slots and slots > 1 else None)
    rf = _num(l.get("ram_free_slots"))
    return _combine([_ram_layout(l), (1.0 if rf > 0 else 0.0) if rf is not None else None, stor,
                     _lin(l.get("repairability_rating"), 1, 10)])

ALL = {"Travel": travel, "College": college, "Developer": developer, "Creator": creator, "Upgrade path": upgrade_path}
def all_scores(l): return {k: f(l) for k, f in ALL.items()}
