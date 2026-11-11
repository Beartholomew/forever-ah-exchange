"""Check which WoW: Forever endpoints actually work, and save what they look like.

    python -m ahtracker.probe                      # auction + item endpoints
    python -m ahtracker.probe --character Name-Surname

Writes data/probe_report.json. Share that file (it contains no secrets) so the
code can be adjusted to the real response shapes.
"""
from __future__ import annotations

import argparse
import json

from .blizzard import BlizzardClient, BlizzardError, find_static_namespace
from .config import DATA_DIR, load_settings


def shape(obj, depth=0):
    """Summarize JSON structure without dumping 9 MB of auctions."""
    if depth > 3:
        return "..."
    if isinstance(obj, dict):
        return {k: shape(v, depth + 1) for k, v in list(obj.items())[:25]}
    if isinstance(obj, list):
        return [f"list[{len(obj)}]", shape(obj[0], depth + 1)] if obj else "list[0]"
    return type(obj).__name__ if not isinstance(obj, (str, int, float)) else obj if len(str(obj)) < 120 else str(obj)[:120]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--character", help="Forever character as Name-Surname")
    args = ap.parse_args()
    s = load_settings()
    c = BlizzardClient(s)
    report: dict = {}

    def attempt(label, fn):
        try:
            js = fn()
            report[label] = {"ok": True, "shape": shape(js)}
            print(f"OK    {label}")
            return js
        except BlizzardError as e:
            report[label] = {"ok": False, "status": e.status, "url": e.url.split("access_token")[0]}
            print(f"FAIL  {label}  -> HTTP {e.status}")
            return None

    c.token()
    print("OK    oauth token")
    rs = attempt("ruleset index", lambda: c.dyn("/data/wow/ruleset/index"))
    report["static_namespace_found"] = find_static_namespace(rs) if rs else None
    rulesets = (rs or {}).get("rulesets") or (rs or {}).get("results") or []
    if rulesets:
        rid = rulesets[0]["id"]
        attempt(f"ruleset {rid}", lambda: c.dyn(f"/data/wow/ruleset/{rid}"))
        idx = attempt("auction house index", lambda: c.dyn(f"/data/wow/ruleset/{rid}/auctions/"))
        for h in (idx or {}).get("auctions", []):
            hid = h["id"]
            js = attempt(f"house {hid} ({h.get('name')}) auctions", lambda: c.house_auctions(rid, hid))
            attempt(f"house {hid} commodities", lambda: c.house_commodities(rid, hid))
            if js and js.get("auctions") and not report.get("static_namespace_found"):
                report["static_namespace_found"] = find_static_namespace(js)
    try:
        ns = c.static_namespace()
        report["static_namespace_used"] = ns
        attempt("item 2770 (Copper Ore)", lambda: c.item(2770))
        attempt("item media 2770", lambda: c.item_media(2770))
        attempt("profession index", lambda: c.static("/data/wow/profession/index"))
    except SystemExit as e:
        report["static_namespace_used"] = str(e)
        print("FAIL  static namespace:", e)
    attempt("wow token price", lambda: c.dyn("/data/wow/token/index"))
    if args.character:
        attempt(f"character professions {args.character}", lambda: c.character_professions(args.character))

    out = DATA_DIR / "probe_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
