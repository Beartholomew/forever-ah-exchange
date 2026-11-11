"""Build the online (static) dashboard from the database.

    python -m ahtracker.build_site --out site

Writes:
  site/index.html                       dashboard page (reads the JSON below)
  site/static/chart.umd.min.js
  site/data/meta.json                   houses, professions, build time
  site/data/overview_<house>.json       top lists, item list, every craft pathway
  site/data/conversions_<house>.json    essence split/combine
  site/data/items/<house>/<id>.json     14 days of hourly history per item (compact)
Characters and professions live in each visitor's browser on the online version.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from . import analytics, db as dbmod, service
from .config import ROOT, load_settings

ALL_SKILLS = {p: 300 for p in service.PROFESSIONS}


def _dump(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, separators=(",", ":")), encoding="utf-8")


def compact_series(rows: list[dict]) -> dict:
    """Hourly rows -> {t0, step, min, mkt, qty, sold} arrays with nulls for missing hours."""
    if not rows:
        return {"t0": 0, "step": 3600, "min": [], "mkt": [], "qty": [], "sold": []}
    t0, t1 = rows[0]["ts"], rows[-1]["ts"]
    n = (t1 - t0) // 3600 + 1
    out = {"t0": t0, "step": 3600, "min": [None] * n, "mkt": [None] * n, "qty": [None] * n, "sold": [None] * n}
    for r in rows:
        i = (r["ts"] - t0) // 3600
        out["min"][i], out["mkt"][i], out["qty"][i], out["sold"][i] = r["min_price"], r["market_price"], r["qty"], r["est_sold"]
    return out


def build(db_path: Path, out: Path, days: int = 14) -> dict:
    s = load_settings()
    con = dbmod.connect(db_path)
    if out.exists():
        shutil.rmtree(out)
    (out / "static").mkdir(parents=True)
    static = ROOT / "web" / "static"
    shutil.copy(static / "chart.umd.min.js", out / "static" / "chart.umd.min.js")
    html = (static / "index.html").read_text(encoding="utf-8")
    html = html.replace('<script src="/static/chart.umd.min.js"></script>',
                        '<script src="static/chart.umd.min.js"></script>\n<script>window.SITE = true;</script>')
    (out / "index.html").write_text(html, encoding="utf-8")
    (out / ".nojekyll").write_text("")

    houses = service.houses(con)
    default = next((h["house_key"] for h in houses if s.default_house.lower() in h["name"].lower()),
                   houses[0]["house_key"] if houses else None)
    _dump(out / "data" / "meta.json", {"sample": False, "houses": houses, "default_house": default,
                                         "professions": service.PROFESSIONS, "built": int(time.time()),
                                         "sync_url": os.environ.get("SYNC_URL", "")})
    all_stats = {h["house_key"]: analytics.compute_stats(con, h["house_key"]) for h in houses}
    counts = {}
    for h in houses:
        key, stats = h["house_key"], all_stats[h["house_key"]]
        cut = s.cut_for(h["name"])
        last = con.execute("SELECT MAX(ts) FROM item_hour WHERE house_key=?", (key,)).fetchone()[0]
        ov = {"house": key, "ah_cut": cut, "last_update": last,
              "tops": analytics.top_lists(stats, s, cut),
              "crafts_all": analytics.craft_pathways(stats, ALL_SKILLS, s, cut, near=300),
              "items": sorted(({"item_id": st.item_id, "name": st.name or f"Item {st.item_id}", "price": st.price,
                                "min_price": st.min_price, "qty": st.qty, "pct_vs7": st.pct_vs7, "verdict": st.verdict,
                                "quality": st.quality, "icon": st.icon, "item_class": st.item_class,
                                "vendor_sell": st.vendor_sell, "daily_sold": round(st.daily_sold, 1)}
                               for st in stats.values()), key=lambda x: x["name"])}
        _dump(out / "data" / f"overview_{key}.json", ov)

        by_item: dict[int, list[dict]] = {}
        for r in con.execute("SELECT item_id, ts, min_price, market_price, qty, est_sold FROM item_hour "
                             "WHERE house_key=? AND ts > ? ORDER BY item_id, ts", (key, (last or 0) - days * 86400)):
            by_item.setdefault(r["item_id"], []).append(dict(r))
        for item_id, st in stats.items():
            d = st.to_dict()
            if st.min_price:
                d["break_even"] = analytics.break_even(st.min_price, cut)
            d["other_houses"] = [{"name": o["name"], "market_price": all_stats[o["house_key"]][item_id].price,
                                  "qty": all_stats[o["house_key"]][item_id].qty}
                                 for o in houses if item_id in all_stats[o["house_key"]]]
            d["ah_cut"] = cut
            d["series_c"] = compact_series(by_item.get(item_id, []))
            _dump(out / "data" / "items" / key / f"{item_id}.json", d)
        counts[key] = len(stats)
    return counts


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=None)
    ap.add_argument("--out", default=str(ROOT / "site"))
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    db_path = Path(a.db) if a.db else load_settings().db_path
    counts = build(db_path, Path(a.out), a.days)
    print("Built site:", counts)


if __name__ == "__main__":
    main()
