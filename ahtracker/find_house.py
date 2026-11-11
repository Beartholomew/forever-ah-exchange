"""Find which auction houses are yours, and check the item-data namespace.

    python -m ahtracker.find_house

Each Forever ruleset (PvE, PvP, ...) has several Alliance/Horde/Blackwater houses,
apparently one set per server partition. This prints, for every Alliance house in your
ruleset, the cheapest price and amount listed for a few common items. Compare those with
what you see on the auction house in game to tell which one is yours.
"""
from __future__ import annotations

import json

from .blizzard import BlizzardClient, BlizzardError
from .config import DATA_DIR, load_settings
from .sales import aggregate, normalize

MARKERS = {2589: "Linen Cloth", 2770: "Copper Ore", 2447: "Peacebloom", 2318: "Light Leather", 4306: "Silk Cloth"}


def g(copper):
    if copper is None:
        return "-"
    gold, rest = divmod(int(copper), 10000)
    s, c = divmod(rest, 100)
    return f"{gold}g {s}s {c}c" if gold else f"{s}s {c}c"


def main() -> None:
    s = load_settings()
    c = BlizzardClient(s)
    report: dict = {}

    print("Rulesets:")
    rs = c.rulesets()
    for r in rs:
        print(f"  id {r['id']}: {r['name']}")
    report["rulesets"] = rs
    ruleset = c.pick_ruleset()
    rid = int(ruleset["id"])
    print(f"\nUsing ruleset {rid} ({ruleset['name']}). Change RULESET_NAME in settings.env if that's wrong.\n")

    try:
        ns = c.static_namespace()
        name = c.item(2589).get("name")
        print(f"Item data namespace works: {ns} (item 2589 = {name})")
        report["static_namespace"] = ns
    except SystemExit as e:
        print("Item data namespace: NOT FOUND -", e)
        report["static_namespace"] = None

    houses = c.houses(rid)
    report["houses"] = []
    want = s.default_house.lower()
    print(f"\nHouses in {ruleset['name']} (checking every '{s.default_house}' one; this takes a minute):")
    for h in houses:
        hid, hname = int(h["id"]), h.get("name", "")
        row = {"id": hid, "name": hname}
        if want not in hname.lower():
            print(f"  #{hid} {hname}")
            report["houses"].append(row)
            continue
        try:
            items = normalize(c.house_auctions(rid, hid).get("auctions", []), commodity=False)
            com = normalize(c.house_commodities(rid, hid).get("auctions", []), commodity=True)
        except BlizzardError as e:
            print(f"  #{hid} {hname}: error {e.status}")
            continue
        stats = aggregate(items + com)
        row["listings"] = len(items) + len(com)
        row["markers"] = {MARKERS[i]: {"cheapest": stats[i]["min_price"], "qty": stats[i]["qty"]} for i in MARKERS if i in stats}
        report["houses"].append(row)
        print(f"\n  #{hid} {hname}: {row['listings']:,} listings")
        if not row["listings"]:
            print("      (empty - probably not used)")
        for label, m in row["markers"].items():
            print(f"      {label:<14} cheapest {g(m['cheapest']):>12}   {m['qty']:,} listed")

    out = DATA_DIR / "find_house_report.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nSaved {out}")
    print("Next: in game, open the AH and search one of these items (e.g. Linen Cloth).")
    print("The house whose cheapest price and amount match what you see is yours.")


if __name__ == "__main__":
    main()
