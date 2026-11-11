"""Data functions shared by the web app and the static demo export."""
from __future__ import annotations

import json
import sqlite3

from . import analytics
from .config import DATA_DIR, Settings

PROFESSIONS = ["Alchemy", "Blacksmithing", "Enchanting", "Engineering", "Herbalism", "Leatherworking",
               "Mining", "Skinning", "Tailoring", "Cooking", "First Aid", "Fishing"]
PROFILES_PATH = DATA_DIR / "profiles.json"


def houses(con: sqlite3.Connection) -> list[dict]:
    return [dict(r) for r in con.execute("SELECT house_key, name FROM houses ORDER BY house_id")]


def house_name(con: sqlite3.Connection, key: str) -> str:
    r = con.execute("SELECT name FROM houses WHERE house_key=?", (key,)).fetchone()
    return r["name"] if r else key


def load_profiles() -> dict:
    try:
        return json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"characters": []}


def save_profiles(data: dict) -> None:
    clean = {"characters": []}
    for c in data.get("characters", []):
        profs = [{"name": p["name"], "skill": max(0, min(300, int(p.get("skill") or 0)))}
                 for p in c.get("professions", []) if p.get("name") in PROFESSIONS]
        entry = {"id": str(c.get("id") or c.get("label", "char")).lower().replace(" ", "-"),
                 "label": str(c.get("label", "Character"))[:40],
                 "name_surname": str(c.get("name_surname", ""))[:60],
                 "professions": profs}
        for k in ("avatar", "render", "summary"):  # filled in by Sync
            if c.get(k):
                entry[k] = c[k] if k == "summary" else str(c[k])[:500]
        clean["characters"].append(entry)
    PROFILES_PATH.write_text(json.dumps(clean, indent=2), encoding="utf-8")


def overview(con: sqlite3.Connection, s: Settings, house_key: str, profiles: dict) -> dict:
    cut = s.cut_for(house_name(con, house_key))
    stats = analytics.compute_stats(con, house_key)
    last = con.execute("SELECT MAX(ts) FROM item_hour WHERE house_key=?", (house_key,)).fetchone()[0]
    crafts = {}
    for c in profiles.get("characters", []):
        profs = {p["name"]: p["skill"] for p in c.get("professions", [])}
        crafts[c["id"]] = analytics.craft_pathways(stats, profs, s, cut)[:10]
    return {"house": house_key, "ah_cut": cut, "last_update": last,
            "tops": analytics.top_lists(stats, s, cut), "crafts": crafts,
            "items": sorted(({"item_id": st.item_id, "name": st.name or f"Item {st.item_id}", "price": st.price,
                              "min_price": st.min_price, "qty": st.qty, "pct_vs7": st.pct_vs7, "verdict": st.verdict,
                              "quality": st.quality, "icon": st.icon, "item_class": st.item_class,
                              "vendor_sell": st.vendor_sell, "daily_sold": round(st.daily_sold, 1)}
                             for st in stats.values()),
                            key=lambda x: x["name"])}


def item_detail(con: sqlite3.Connection, s: Settings, house_key: str, item_id: int, days: int = 30) -> dict:
    cut = s.cut_for(house_name(con, house_key))
    st = analytics.compute_stats(con, house_key, [item_id]).get(item_id)
    series = [dict(r) for r in con.execute(
        "SELECT ts, min_price, market_price, qty, est_sold FROM item_hour WHERE house_key=? AND item_id=? "
        "AND ts > (SELECT MAX(ts) FROM item_hour WHERE house_key=?) - ? ORDER BY ts",
        (house_key, item_id, house_key, days * 86400))]
    other = [dict(r) for r in con.execute(
        "SELECT h.name, ih.market_price, ih.qty FROM item_hour ih JOIN houses h ON h.house_key = ih.house_key "
        "WHERE ih.item_id=? AND ih.ts = (SELECT MAX(ts) FROM item_hour x WHERE x.house_key = ih.house_key) ORDER BY h.house_id",
        (item_id,))]
    d = st.to_dict() if st else {"item_id": item_id}
    if st and st.min_price:
        d["break_even"] = analytics.break_even(st.min_price, cut)
        d["net_at_market"] = analytics.net(st.price or 0, cut)
    d.update({"series": series, "other_houses": other, "ah_cut": cut})
    return d


CONVERSIONS_PATH = DATA_DIR / "conversions.json"


def load_conversions() -> list[dict]:
    try:
        return json.loads(CONVERSIONS_PATH.read_text(encoding="utf-8"))["conversions"]
    except FileNotFoundError:
        return []


def conversions(con: sqlite3.Connection, s: Settings, house_key: str, days: int = 14) -> list[dict]:
    """Split (1 big -> N small) and combine (N small -> 1 big) profit, now and over time.
    Buys use the cheapest listing, sells use the market price, AH cut applied to the sale."""
    cut = s.cut_for(house_name(con, house_key))
    pairs = load_conversions()
    ids = sorted({p["big"] for p in pairs} | {p["small"] for p in pairs})
    if not ids:
        return []
    stats = analytics.compute_stats(con, house_key, ids)
    last = con.execute("SELECT MAX(ts) FROM item_hour WHERE house_key=?", (house_key,)).fetchone()[0] or 0
    rows: dict[int, dict[int, dict]] = {}
    for r in con.execute(
            f"SELECT item_id, ts, min_price, market_price FROM item_hour WHERE house_key=? AND ts > ? "
            f"AND item_id IN ({','.join(map(str, ids))})", (house_key, last - days * 86400)):
        rows.setdefault(r["item_id"], {})[r["ts"]] = dict(r)
    out = []
    for p in pairs:
        big, small, n = stats.get(p["big"]), stats.get(p["small"]), int(p.get("ratio", 3))
        if not big or not small or not big.price or not small.price:
            continue
        split = n * small.price * (1 - cut) - (big.min_price or big.price)
        combine = big.price * (1 - cut) - n * (small.min_price or small.price)
        series = []
        bigs, smalls = rows.get(p["big"], {}), rows.get(p["small"], {})
        for ts in sorted(set(bigs) & set(smalls)):
            b, sm = bigs[ts], smalls[ts]
            if not (b["market_price"] and sm["market_price"]):
                continue
            series.append({"ts": ts,
                           "split": round(n * sm["market_price"] * (1 - cut) - (b["min_price"] or b["market_price"])),
                           "combine": round(b["market_price"] * (1 - cut) - n * (sm["min_price"] or sm["market_price"]))})
        recent = [x["split"] for x in series if x["ts"] > last - 7 * 86400]
        avg_split = sum(recent) / len(recent) if recent else None
        buy_in = big.min_price or big.price
        verdict = "Wait"
        if split > 0 and split / buy_in >= 0.05:
            verdict = "Split now"
        elif combine > 0 and combine / (n * (small.min_price or small.price)) >= 0.05:
            verdict = "Combine now"
        out.append({
            "name": p["name"], "ratio": n,
            "big": {"item_id": big.item_id, "name": big.name or f"Item {big.item_id}", "quality": big.quality,
                    "icon": big.icon, "cheapest": big.min_price, "price": big.price, "daily_sold": round(big.daily_sold, 1)},
            "small": {"item_id": small.item_id, "name": small.name or f"Item {small.item_id}", "quality": small.quality,
                      "icon": small.icon, "cheapest": small.min_price, "price": small.price, "daily_sold": round(small.daily_sold, 1)},
            "split_profit": round(split), "split_roi": split / buy_in if buy_in else None,
            "combine_profit": round(combine), "avg_split_7d": round(avg_split) if avg_split is not None else None,
            "verdict": verdict, "ah_cut": cut, "series": series,
        })
    out.sort(key=lambda x: max(x["split_profit"], x["combine_profit"]), reverse=True)
    return out
