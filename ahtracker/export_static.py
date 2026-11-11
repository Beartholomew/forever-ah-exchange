"""Build a single self-contained HTML demo of the dashboard (no server needed).
    python -m ahtracker.export_static [--db data/sample.sqlite] [--out demo.html] [--days 14]
Profile edits in the demo are saved in the browser only; craft suggestions there are precomputed.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import db as dbmod, service
from .config import DATA_DIR, ROOT, load_settings

DEMO_PROFILES = {"characters": [
    {"id": "main", "label": "Main (Mining 70, First Aid 120)", "name_surname": "",
     "professions": [{"name": "Mining", "skill": 70}, {"name": "First Aid", "skill": 120}]},
    {"id": "alt", "label": "Alt (Tailoring 80, Herbalism 60)", "name_surname": "",
     "professions": [{"name": "Tailoring", "skill": 80}, {"name": "Herbalism", "skill": 60}]},
]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DATA_DIR / "sample.sqlite"))
    ap.add_argument("--out", default=str(ROOT / "demo.html"))
    ap.add_argument("--days", type=int, default=14)
    a = ap.parse_args()
    s = load_settings()
    con = dbmod.connect(a.db)
    hs = service.houses(con)
    data = {"meta": {"sample": True, "houses": hs, "professions": service.PROFESSIONS},
            "profiles": DEMO_PROFILES, "overviews": {}, "items": {}, "conversions": {}}
    for h in hs:
        k = h["house_key"]
        ov = service.overview(con, s, k, DEMO_PROFILES)
        data["overviews"][k] = ov
        data["conversions"][k] = service.conversions(con, s, k)
        data["items"][k] = {str(i["item_id"]): service.item_detail(con, s, k, i["item_id"], a.days) for i in ov["items"]}
    static = ROOT / "web" / "static"
    html = (static / "index.html").read_text(encoding="utf-8")
    chart = (static / "chart.umd.min.js").read_text(encoding="utf-8")
    blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
    html = html.replace('<script src="/static/chart.umd.min.js"></script>',
                        f"<script>{chart}</script>\n<script>window.STATIC={blob};</script>")
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"Wrote {a.out} ({len(html) / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
