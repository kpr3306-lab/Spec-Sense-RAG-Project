"""Non-printing facade over the engines, for the Streamlit frontend (and a future FastAPI layer)."""
import sqlite3
from datetime import date
import recommendation_engine as R
import accessory_engine as A


def evidence_for(kb, vec, req, laptop, k=1):
    out, seen = [], set()
    for w in req.get("required_workloads", []) + req.get("soft_workloads", []):
        out += R.kb_query(kb, vec, w.replace("_", " "), k=k, collection_filter="workload_requirements")
    gpu = laptop.get("gpu_model") or "integrated graphics"
    out += R.kb_query(kb, vec, f"{gpu} {laptop.get('ram_type') or ''} battery Wh", k=1,
                      collection_filter="hardware_glossary")
    return [e for e in out if not (e["doc_id"] in seen or seen.add(e["doc_id"]))]


def weakest_dimension(c, weights=None, req=None):
    """Biggest real compromise: lowest *known* dimension that the user cares about, and only if it is
    actually weak (<0.45). Unknown dims are never blamed; brand/colour only counts if a preference was set."""
    w = weights or R.DEFAULT_WEIGHTS
    req = req or {}
    cands = {}
    for k, v in c["dims"].items():
        if v is None or w.get(k, 0) <= 0.01:
            continue
        if k == "brand_colour" and not (req.get("preferred_brands") or req.get("preferred_colours")):
            continue
        cands[k] = v
    if not cands:
        return None
    k = min(cands, key=cands.get)
    return k if cands[k] < 0.45 else None


def run(laptops, req, kb, vec, top_n=4, weights=None):
    passed, rejected = R.hard_filter(laptops, req)
    res = {"passed": len(passed), "total": len(laptops), "rejected": rejected,
           "candidates": [], "compromises": [], "smart": None, "tradeoffs": []}
    if not passed:
        res["compromises"] = R.closest_compromises(laptops, req)
    else:
        top = R.rerank_diverse(R.score_candidates(passed, req, weights), top_n=top_n)
        for c in top:
            acc = A.recommend_accessories(c, req, kb, vec)
            for a in acc:
                a["price_inr"] = A.ACCESSORY_CATALOG.get(a["key"], {}).get("price_inr")
            c["evidence"] = evidence_for(kb, vec, req, c)
            c["accessories"] = acc
            c["cost"] = A.hidden_cost_breakdown(c, acc)
            c["weakest"] = weakest_dimension(c, weights, req)
        res["candidates"] = top
        if len(top) >= 2:
            res["tradeoffs"] = R.trade_off_note(top[0], top[1]) + R.trade_off_note(top[1], top[0])
    res["smart"] = R.best_for_workload_overall(laptops, req)
    return res


def save_price(sku, price, retailer, url, observed=None, note=None):
    """Touches only live-price columns. observed = date the price was seen (defaults to today)."""
    con = sqlite3.connect(R.DB_PATH)
    con.execute("UPDATE laptops SET observed_price_inr=?, retailer_name=?, price_source_url=?, "
                "price_last_checked_date=?, price_note=? WHERE sku_id=?",
                (price, retailer, url, observed or str(date.today()), note, sku))
    con.commit(); con.close()
