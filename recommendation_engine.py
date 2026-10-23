"""
SpecSense MVP3 — Weighted recommendation engine.

Implements the blueprint's Stage A-E pipeline on top of the MVP1 database and
MVP2 knowledge base, plus the user's two requested additions:
  - colour as a filterable/scored soft preference
  - a "best overall for your workload, irrespective of budget" recommendation

Stage A — Hard filter (budget, weight, RAM, ports, OS, workload fit)
Stage B — Fit scoring (performance, display, portability,
           connectivity, upgradeability, service, brand/colour), weighted
           by user-supplied weights
Stage C — RAG evidence (pulls supporting chunks from the MVP2 knowledge base)
Stage D — Reranking for diversity (top 3-5, not near-duplicates)
Stage E — Explanation (trade-off template using only retrieved evidence +
           the candidate's own structured specs — no invented claims)

Run: python3 recommendation_engine.py
"""

import sqlite3
import pickle
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent  # project root (parent of src/)
DB_PATH = str(BASE_DIR / "data" / "specsense.db")
CHROMA_PATH = str(BASE_DIR / "vector_store" / "chroma_db")
COLLECTION_NAME = "specsense_kb"

GPU_HEAVY_WORKLOADS = {"gaming", "content_creation", "ml_dl", "cad_engineering"}

DEFAULT_WEIGHTS = {
    "performance": 0.30,
    "display": 0.10,
    "portability": 0.15,
    "connectivity": 0.10,
    "upgradeability": 0.05,
    "service": 0.05,
    "brand_colour": 0.10,
}


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_laptops():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM laptops").fetchall()
    conn.close()
    laptops = [dict(r) for r in rows]
    for l in laptops:
        l["workload_tags_list"] = [t.strip() for t in (l["workload_tags"] or "").split(",") if t.strip()]
    return laptops


def load_kb():
    import chromadb  # only the knowledge base needs it; the catalogue works without
    client = chromadb.PersistentClient(path=CHROMA_PATH)
    collection = client.get_collection(COLLECTION_NAME)
    with open(f"{CHROMA_PATH}/vectorizer.pkl", "rb") as f:
        vectorizer = pickle.load(f)
    return collection, vectorizer


def kb_query(collection, vectorizer, question, k=2, collection_filter=None):
    if collection is None:  # knowledge base not built yet -> no evidence, never invented
        return []
    q_vec = vectorizer.transform([question]).toarray().tolist()
    where = {"collection": collection_filter} if collection_filter else None
    results = collection.query(query_embeddings=q_vec, n_results=k, where=where)
    return [
        {"doc_id": m["doc_id"], "section": m["section_title"], "text": d}
        for d, m in zip(results["documents"][0], results["metadatas"][0])
    ]


# ---------------------------------------------------------------------------
# Stage A — Hard filter
# ---------------------------------------------------------------------------

def hard_filter(laptops, req, ignore_budget=False):
    """Apply only constraints that have meaningful catalogue values.

    A missing/zero field is treated as unknown rather than as a real zero.
    Required constraints remain strict when the product data is known.
    """
    passed, rejected = [], []
    for l in laptops:
        reasons = []
        price = _num(l.get("observed_price_inr")) or _num(l.get("msrp_inr"))
        weight = _num(l.get("weight_kg"))
        ram = _num(l.get("ram_gb"))
        usb_a = _num(l.get("usb_a_count"))
        slots = _num(l.get("storage_slots"))
        os = str(l.get("os") or "")

        if not ignore_budget and req.get("budget_max") and price is not None and price > req["budget_max"]:
            reasons.append(f"over budget (₹{price:,.0f} > ₹{req['budget_max']:,.0f})")
        if req.get("weight_max_kg") and weight is not None and weight > req["weight_max_kg"]:
            reasons.append(f"too heavy ({weight}kg > {req['weight_max_kg']}kg)")
        if req.get("ram_min_gb") and ram is not None and ram < req["ram_min_gb"]:
            reasons.append(f"insufficient RAM ({ram:g}GB < {req['ram_min_gb']}GB)")
        if req.get("usb_a_required") and usb_a is not None and usb_a < 1:
            reasons.append("no USB-A port")
        if req.get("min_storage_slots") and slots is not None and slots < req["min_storage_slots"]:
            reasons.append(f"insufficient M.2 slots ({slots:g} < {req['min_storage_slots']} )")
        if req.get("os") and req["os"].lower() not in os.lower():
            reasons.append(f"OS mismatch ({os or 'unknown'})")
        for w in req.get("required_workloads", []):
            if l["workload_tags_list"] and w not in l["workload_tags_list"]:  # untagged = unknown, not unsuitable
                reasons.append(f"not well-suited for '{w}'")
        if reasons:
            rejected.append({**l, "reasons": reasons})
        else:
            passed.append(l)
    return passed, rejected


def closest_compromises(laptops, req):
    """When Stage A yields nothing: relax constraints one at a time and report what unlocks matches."""
    relaxations = []

    if req.get("budget_max"):
        for pct in (0.10, 0.20, 0.35):
            relaxed = {**req, "budget_max": req["budget_max"] * (1 + pct)}
            passed, _ = hard_filter(laptops, relaxed)
            if passed:
                relaxations.append((f"raise budget by {int(pct*100)}% (to ₹{relaxed['budget_max']:,.0f})",
                                     len(passed)))
                break

    if req.get("weight_max_kg"):
        for delta in (0.2, 0.4, 0.6):
            relaxed = {**req, "weight_max_kg": req["weight_max_kg"] + delta}
            passed, _ = hard_filter(laptops, relaxed)
            if passed:
                relaxations.append((f"raise weight limit by {delta}kg (to {relaxed['weight_max_kg']}kg)",
                                     len(passed)))
                break

    if req.get("required_workloads") and len(req["required_workloads"]) > 1:
        for w in req["required_workloads"]:
            relaxed = {**req, "required_workloads": [x for x in req["required_workloads"] if x != w]}
            passed, _ = hard_filter(laptops, relaxed)
            if passed:
                relaxations.append((f"drop the '{w}' workload requirement", len(passed)))
                break

    return relaxations


# ---------------------------------------------------------------------------
# Stage B — Fit scoring
# ---------------------------------------------------------------------------

def _num(v, default=None):
    """Return a usable finite number; treat 0/blank/NULL as unknown."""
    try:
        if v is None or v == "":
            return default
        x = float(v)
        return default if x == 0 else x
    except (TypeError, ValueError):
        return default


def _minmax_known(values, higher_is_better=True, neutral=0.5):
    """Min-max score only known values. Unknown values remain None."""
    known = [v for v in values if v is not None]
    if not known:
        return [None] * len(values)
    lo, hi = min(known), max(known)
    if hi == lo:
        return [neutral if v is not None else None for v in values]
    out = []
    for v in values:
        if v is None:
            out.append(None)
        else:
            s = (v - lo) / (hi - lo)
            out.append(s if higher_is_better else 1 - s)
    return out


def _weighted_known(dim_scores, weights):
    """Reweight across dimensions that actually have usable data."""
    known = [(k, dim_scores[k], weights[k]) for k in weights
             if dim_scores.get(k) is not None]
    if not known:
        return 0.5, 0.0
    total_w = sum(w for _, _, w in known)
    score = sum(s * w for _, s, w in known) / total_w
    coverage = total_w / sum(weights.values())
    return score, coverage


def _performance_score(candidates, gpu_heavy):
    cpu_values = [_num(c.get("cpu_cores")) * _num(c.get("cpu_threads"))
                  if _num(c.get("cpu_cores")) is not None and _num(c.get("cpu_threads")) is not None else None
                  for c in candidates]
    ram_values = [_num(c.get("ram_gb")) for c in candidates]

    # VRAM is useful, but model/class is more important than VRAM alone.
    gpu_values = []
    for c in candidates:
        if str(c.get("gpu_type", "")).lower() == "discrete":
            vram = _num(c.get("gpu_vram_gb"))
            gpu_values.append(vram)
        else:
            gpu_values.append(0.0)

    cpu_s = _minmax_known(cpu_values)
    ram_s = _minmax_known(ram_values)
    gpu_s = _minmax_known(gpu_values)

    result = []
    for i, c in enumerate(candidates):
        # For GPU-heavy work, discrete GPU presence + VRAM gets strong weight.
        discrete = str(c.get("gpu_type", "")).lower() == "discrete"
        if gpu_heavy:
            parts = [
                ("gpu", gpu_s[i], 0.50 if discrete else 0.15),
                ("cpu", cpu_s[i], 0.30),
                ("ram", ram_s[i], 0.20),
            ]
        else:
            parts = [
                ("cpu", cpu_s[i], 0.45),
                ("ram", ram_s[i], 0.35),
                ("gpu", gpu_s[i], 0.20),
            ]
        known = [(s, w) for _, s, w in parts if s is not None]
        if not known:
            result.append(None)
        else:
            result.append(sum(s * w for s, w in known) / sum(w for s, w in known))
    return result


def score_candidates(candidates, req, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    if not candidates:
        return []

    workloads = set(req.get("required_workloads", []) + req.get("soft_workloads", []))
    gpu_heavy = bool(workloads & GPU_HEAVY_WORKLOADS)

    perf = _performance_score(candidates, gpu_heavy)
    brightness = _minmax_known([_num(c.get("display_brightness_nits")) for c in candidates])
    refresh = _minmax_known([_num(c.get("display_refresh_hz")) for c in candidates])
    portability = _minmax_known([_num(c.get("weight_kg")) for c in candidates],
                                higher_is_better=False)
    def _port_value(c):
        """Absolute port richness. Unknown stays None (never 0); only known fields count."""
        parts = [(_num(c.get("usb_a_count")), 1), (_num(c.get("usb_c_count")), 1),
                 (_num(c.get("thunderbolt_usb4")), 2), (_num(c.get("sd_card_reader")), .5),
                 (_num(c.get("ethernet_port")), .5), (_num(c.get("hdmi_version")), .5)]
        if _num(c.get("usb_a_count")) is None and _num(c.get("usb_c_count")) is None:
            return None  # USB counts unknown -> don't score (extras alone would be misleading)
        total = sum((min(v, 3) if w == 1 else w * (1 if v else 0)) for v, w in parts if v is not None)
        return min(1.0, total / 5.0)
    ports = [_port_value(c) for c in candidates]
    upgrade_values = []
    for c in candidates:
        ram_up = _num(c.get("ram_upgradeable"))
        slots = _num(c.get("storage_slots"))
        if ram_up is None and slots is None:
            upgrade_values.append(None)
        else:
            upgrade_values.append((ram_up or 0) + (1 if slots is not None and slots > 1 else 0))
    upgrade = _minmax_known(upgrade_values)
    service_values = []
    for c in candidates:
        warranty = _num(c.get("warranty_years"))
        onsite = _num(c.get("onsite_support"))
        if warranty is None and onsite is None:
            service_values.append(None)
        else:
            service_values.append((warranty or 0) + (onsite or 0))
    service = _minmax_known(service_values)

    brand_pref = [b.lower() for b in req.get("preferred_brands", [])]
    colour_pref = [c.lower() for c in req.get("preferred_colours", [])]

    scored = []
    for i, c in enumerate(candidates):
        if brand_pref:
            brand_score = 0.6 if str(c.get("brand", "")).lower() in brand_pref else 0.0
        else:
            brand_score = 0.3
        if colour_pref:
            colour_score = 0.4 if str(c.get("colour", "")).lower() in colour_pref else 0.0
        else:
            colour_score = 0.2
        brand_colour_score = brand_score + colour_score

        display_parts = [(brightness[i], 0.5), (refresh[i], 0.5)]
        display_known = [(s, w) for s, w in display_parts if s is not None]
        display_score = (sum(s * w for s, w in display_known) / sum(w for _, w in display_known)
                         if display_known else None)

        dims = {
            "performance": perf[i],
            "display": display_score,
            "portability": portability[i],
            "connectivity": ports[i],
            "upgradeability": upgrade[i],
            "service": service[i],
            "brand_colour": brand_colour_score,
        }

        total, coverage = _weighted_known(dims, weights)
        # Small confidence adjustment: incomplete records cannot outrank equally
        # strong complete records simply because missing values were ignored.
        confidence = _num(c.get("data_confidence_score"))
        confidence_factor = (0.90 + 0.10 * confidence / 100) if confidence is not None else 0.95
        final = total * confidence_factor

        scored.append({
            **c,
            "dims": dims,
            "score_coverage": coverage,
            "data_confidence_factor": confidence_factor,
            "fit_score": round(final * 100, 1),
        })

    scored.sort(key=lambda x: x["fit_score"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Stage D — Reranking for diversity
# ---------------------------------------------------------------------------

def rerank_diverse(scored, top_n=5, max_per_brand=2):
    chosen, brand_count = [], {}
    for c in scored:
        b = c["brand"]
        if brand_count.get(b, 0) >= max_per_brand:
            continue
        chosen.append(c)
        brand_count[b] = brand_count.get(b, 0) + 1
        if len(chosen) == top_n:
            break
    return chosen


# ---------------------------------------------------------------------------
# Stage C + E — Evidence + trade-off explanation
# ---------------------------------------------------------------------------

def explain_candidate(c, req, kb_collection, kb_vectorizer):
    workloads = req.get("required_workloads", []) + req.get("soft_workloads", [])
    workload_evidence = []
    for w in workloads:
        workload_evidence += kb_query(kb_collection, kb_vectorizer, w.replace("_", " "),
                                       k=1, collection_filter="workload_requirements")
    glossary_evidence = kb_query(kb_collection, kb_vectorizer,
                                  f"{c['gpu_model']} {c['ram_type']} battery Wh", k=1,
                                  collection_filter="hardware_glossary")
    raw_evidence = workload_evidence + glossary_evidence
    seen = set()
    evidence = []
    for e in raw_evidence:
        key = e["doc_id"]
        if key not in seen:
            seen.add(key)
            evidence.append(e)

    price = _num(c.get("observed_price_inr")) or _num(c.get("msrp_inr"))
    price_text = f"₹{price:,.0f}" if price is not None else "Price unavailable"
    print(f"\n  {c['brand']} {c['model_name']} — {price_text} — fit score {c['fit_score']}/100")
    print(f"    CPU: {c['cpu_model']} | GPU: {c['gpu_model']} "
          f"({c['gpu_vram_gb']}GB)" if c['gpu_type'] == 'Discrete' else f"    CPU: {c['cpu_model']} | GPU: Integrated ({c['gpu_model']})")
    ram = _num(c.get("ram_gb")); storage = _num(c.get("storage_gb"))
    weight = _num(c.get("weight_kg")); battery_wh = _num(c.get("battery_wh"))
    battery_hrs = _num(c.get("battery_life_claimed_hrs"))
    print(f"    RAM: {ram:g}GB {c['ram_type']}" if ram is not None else f"    RAM: Unknown {c['ram_type']}")
    print(f"    Storage: {storage:g}GB {c['storage_type']}" if storage is not None else f"    Storage: Unknown {c['storage_type']}")
    print(f"    Weight: {weight:g}kg" if weight is not None else "    Weight: Unknown")
    print(f"    Battery: {battery_wh:g}Wh" if battery_wh is not None else "    Battery: Unknown", end="")
    print(f" (~{battery_hrs:g}h claimed)" if battery_hrs is not None else " (claimed runtime unavailable)")
    refresh_hz = _num(c.get("display_refresh_hz"))
    refresh_text = f"@{refresh_hz:g}Hz" if refresh_hz is not None else "@refresh rate unknown"
    print(f"    Display: {c['display_size_in']}\" {c['display_resolution']} {c['display_panel_type']} "
          f"{refresh_text} | Colour: {c['colour'] or 'unknown'}")
    print(f"    Dimension scores: " + ", ".join(f"{k}={v:.2f}" for k, v in c["dims"].items()))
    print(f"    Supporting evidence: " + "; ".join(f"[{e['doc_id']}]" for e in evidence))
    print(f"    Note: {c['source_note']} (confidence: {c['confidence']})")
    if "data_confidence_score" in c and c["data_confidence_score"] is not None:
        print(f"    Data confidence score: {c['data_confidence_score']}/100 | "
              f"Repairability/upgradeability: {c.get('repairability_rating', 'unknown')}"
              + (f" | Verified source: {c['source_url']}" if c.get("source_url") else ""))


def trade_off_note(a, b):
    notes = []
    aw, bw = _num(a.get("weight_kg")), _num(b.get("weight_kg"))
    if aw is not None and bw is not None and aw < bw - 0.1:
        notes.append(f"{a['model_name']} is lighter ({aw:g}kg vs {bw:g}kg)")

    ab, bb = _num(a.get("battery_wh")), _num(b.get("battery_wh"))
    if ab is not None and bb is not None and ab > bb * 1.1:
        notes.append(f"{a['model_name']} has a larger battery ({ab:g}Wh vs {bb:g}Wh)")

    ag, bg = _num(a.get("gpu_vram_gb")), _num(b.get("gpu_vram_gb"))
    if ag is not None and bg is not None and bg > ag:
        notes.append(f"{b['model_name']} has more GPU VRAM ({bg:g}GB vs {ag:g}GB) for heavier GPU workloads")

    ap = _num(a.get("observed_price_inr")) or _num(a.get("msrp_inr"))
    bp = _num(b.get("observed_price_inr")) or _num(b.get("msrp_inr"))
    if ap is not None and bp is not None and bp < ap * 0.9:
        notes.append(f"{b['model_name']} costs less (₹{bp:,.0f} vs ₹{ap:,.0f})")
    return notes


# ---------------------------------------------------------------------------
# Smart recommendation: best-for-workload, irrespective of budget
# ---------------------------------------------------------------------------

def best_for_workload_overall(laptops, req):
    """Best workload-performance candidate without applying the user's budget."""
    req_no_budget = {**req}
    req_no_budget.pop("budget_max", None)
    candidates, _ = hard_filter(laptops, req_no_budget, ignore_budget=True)
    if not candidates:
        return None

    workloads = set(req.get("required_workloads", []) + req.get("soft_workloads", []))
    gpu_heavy = bool(workloads & GPU_HEAVY_WORKLOADS)
    perf = _performance_score(candidates, gpu_heavy)

    best_idx = max(range(len(candidates)),
                   key=lambda i: (-1 if perf[i] is None else perf[i]))
    best = candidates[best_idx]
    score = perf[best_idx] if perf[best_idx] is not None else 0.5

    price = _num(best.get("observed_price_inr")) or _num(best.get("msrp_inr"))
    budget = req.get("budget_max")
    over_by = (price - budget) if price is not None and budget else None
    return {
        **best,
        "workload_perf_score": round(score * 100, 1),
        "over_budget_by": over_by,
        "over_budget_pct": (over_by / budget * 100) if over_by and budget else None,
    }


# ---------------------------------------------------------------------------
# Pipeline runner
# ---------------------------------------------------------------------------

def recommend(laptops, req, kb_collection, kb_vectorizer, top_n=4):
    print("=" * 78)
    print(f"USER PROFILE: {req}")
    print("=" * 78)

    passed, rejected = hard_filter(laptops, req)
    print(f"\nStage A — hard filter: {len(passed)} of {len(laptops)} candidates pass "
          f"({len(rejected)} rejected).")

    if not passed:
        print("\nNo laptop satisfies every hard constraint. Closest compromises:")
        compromises = closest_compromises(laptops, req)
        if compromises:
            for desc, count in compromises:
                print(f"  - If you {desc}: {count} laptop(s) become available.")
        else:
            print("  - No single relaxation found within the tested ranges either; "
                  "constraints may need a larger rethink.")
        return

    scored = score_candidates(passed, req)
    top = rerank_diverse(scored, top_n=top_n)

    print(f"\nStage B-D — top {len(top)} diverse candidates (fit-scored, weighted):")
    for c in top:
        explain_candidate(c, req, kb_collection, kb_vectorizer)

    if len(top) >= 2:
        print("\nStage E — trade-off notes (top 2):")
        for note in trade_off_note(top[0], top[1]):
            print(f"  - {note}")
        for note in trade_off_note(top[1], top[0]):
            print(f"  - {note}")

    best_overall = best_for_workload_overall(laptops, req)
    if best_overall:
        print(f"\nSmart recommendation — best for your workload, irrespective of budget:")
        overall_price = _num(best_overall.get("observed_price_inr")) or _num(best_overall.get("msrp_inr"))
        overall_price_text = f"₹{overall_price:,.0f}" if overall_price is not None else "Price unavailable"
        print(f"  {best_overall['brand']} {best_overall['model_name']} — "
              f"{overall_price_text} (workload-fit score {best_overall['workload_perf_score']}/100)")
        if best_overall["over_budget_by"] and best_overall["over_budget_by"] > 0:
            print(f"  This is ₹{best_overall['over_budget_by']:,.0f} "
                  f"({best_overall['over_budget_pct']:.0f}%) over your stated budget.")
        elif best_overall["sku_id"] not in [t["sku_id"] for t in top]:
            print(f"  This fits your budget but wasn't in your soft-preference-weighted top {top_n} "
                  f"(likely due to brand/colour/portability trade-offs) — pure workload performance says "
                  f"this is the strongest pick.")
        else:
            print(f"  This is already your #1 budget-constrained pick — no compromise needed.")


if __name__ == "__main__":
    laptops = load_laptops()
    kb_collection, kb_vectorizer = load_kb()

    # Profile 1: student/coder, matches the blueprint's own example constraints
    profile_1 = {
        "budget_max": 80000,
        "weight_max_kg": 1.6,
        "ram_min_gb": 16,
        "usb_a_required": True,
        "required_workloads": ["coding_dev"],
        "soft_workloads": ["student_general"],
        "preferred_brands": ["ASUS", "Lenovo"],
        "preferred_colours": ["Quiet Blue", "Arctic Grey"],
    }
    recommend(laptops, profile_1, kb_collection, kb_vectorizer)

    # Profile 2: ML/DL-focused buyer with a mid-tier budget
    profile_2 = {
        "budget_max": 150000,
        "ram_min_gb": 16,
        "required_workloads": ["ml_dl"],
        "preferred_brands": [],
        "preferred_colours": [],
    }
    recommend(laptops, profile_2, kb_collection, kb_vectorizer)

    # Profile 3: adversarial case (blueprint's own evaluation example)
    profile_3 = {
        "budget_max": 60000,
        "ram_min_gb": 32,
        "weight_max_kg": 1.3,
        "required_workloads": ["cad_engineering"],
        "min_storage_slots": 2,
    }
    recommend(laptops, profile_3, kb_collection, kb_vectorizer)

    # Profile 4: same student/coder use case as Profile 1, slightly loosened constraints
    # (to demonstrate the full Stage B-E happy path with several diverse candidates)
    profile_4 = {
        "budget_max": 100000,
        "weight_max_kg": 1.8,
        "ram_min_gb": 16,
        "usb_a_required": True,
        "required_workloads": ["coding_dev"],
        "soft_workloads": ["student_general"],
        "preferred_brands": ["ASUS", "Lenovo"],
        "preferred_colours": ["Quiet Blue", "Arctic Grey"],
    }
    recommend(laptops, profile_4, kb_collection, kb_vectorizer)
