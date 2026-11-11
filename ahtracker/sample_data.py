"""Fill a database with 30 days of realistic fake data so the dashboard works before
the real collector has run.   python -m ahtracker.sample_data  [--db data/sample.sqlite]

The numbers are invented. Patterns are built in on purpose so every panel has something
to show: daily/weekly rhythms, a launch-style downward drift on leveling mats, two price
spikes, two 'heating up' items, one market reset, and cheap Copper/Linen for craft pathways.
"""
from __future__ import annotations

import argparse
import math
import random
import time
from pathlib import Path

from . import db as dbmod
from .config import DATA_DIR

# item_id, name, class, quality, base price (copper), sold per day, vendor sell, leveling mat?
ITEMS = [
    (2770, "Copper Ore", "Trade Goods", "Common", 900, 900, 5, True),
    (2771, "Tin Ore", "Trade Goods", "Common", 1400, 500, 6, True),
    (2775, "Silver Ore", "Trade Goods", "Uncommon", 4500, 80, 75, True),
    (2772, "Iron Ore", "Trade Goods", "Common", 3800, 350, 150, True),
    (2776, "Gold Ore", "Trade Goods", "Uncommon", 9000, 120, 600, True),
    (3858, "Mithril Ore", "Trade Goods", "Common", 6500, 400, 250, True),
    (10620, "Thorium Ore", "Trade Goods", "Common", 9500, 600, 250, False),
    (2840, "Copper Bar", "Trade Goods", "Common", 1500, 600, 10, True),
    (3576, "Tin Bar", "Trade Goods", "Common", 2000, 300, 25, True),
    (2841, "Bronze Bar", "Trade Goods", "Common", 2900, 350, 50, True),
    (2842, "Silver Bar", "Trade Goods", "Uncommon", 5200, 60, 100, True),
    (3575, "Iron Bar", "Trade Goods", "Common", 4600, 250, 100, True),
    (3577, "Gold Bar", "Trade Goods", "Uncommon", 11000, 90, 600, True),
    (3860, "Mithril Bar", "Trade Goods", "Common", 8000, 300, 100, True),
    (12359, "Thorium Bar", "Trade Goods", "Common", 12500, 400, 600, False),
    (2589, "Linen Cloth", "Trade Goods", "Common", 450, 1500, 13, True),
    (2592, "Wool Cloth", "Trade Goods", "Common", 900, 900, 33, True),
    (4306, "Silk Cloth", "Trade Goods", "Common", 1600, 800, 150, True),
    (4338, "Mageweave Cloth", "Trade Goods", "Common", 3000, 700, 250, True),
    (14047, "Runecloth", "Trade Goods", "Common", 4200, 1200, 400, False),
    (2996, "Bolt of Linen Cloth", "Trade Goods", "Common", 1300, 250, 40, True),
    (2997, "Bolt of Woolen Cloth", "Trade Goods", "Common", 3100, 180, 100, True),
    (4305, "Bolt of Silk Cloth", "Trade Goods", "Common", 7600, 160, 600, True),
    (1251, "Linen Bandage", "Consumable", "Common", 600, 300, 10, True),
    (2581, "Heavy Linen Bandage", "Consumable", "Common", 1200, 250, 20, True),
    (3530, "Wool Bandage", "Consumable", "Common", 1500, 250, 28, True),
    (3531, "Heavy Wool Bandage", "Consumable", "Common", 2600, 220, 50, True),
    (6450, "Silk Bandage", "Consumable", "Common", 2400, 280, 100, True),
    (6451, "Heavy Silk Bandage", "Consumable", "Common", 4300, 260, 200, True),
    (8544, "Mageweave Bandage", "Consumable", "Common", 4100, 300, 200, True),
    (14529, "Runecloth Bandage", "Consumable", "Common", 6800, 500, 400, False),
    (2447, "Peacebloom", "Trade Goods", "Common", 700, 800, 1, True),
    (765, "Silverleaf", "Trade Goods", "Common", 650, 800, 1, True),
    (2453, "Bruiseweed", "Trade Goods", "Common", 2100, 300, 10, True),
    (3356, "Kingsblood", "Trade Goods", "Common", 4800, 200, 30, True),
    (13468, "Black Lotus", "Trade Goods", "Uncommon", 1800000, 15, 1000, False),
    (12363, "Arcane Crystal", "Trade Goods", "Rare", 650000, 12, 1000, False),
    (13452, "Elixir of the Mongoose", "Consumable", "Common", 95000, 70, 300, False),
    (2318, "Light Leather", "Trade Goods", "Common", 800, 700, 15, True),
    (4234, "Heavy Leather", "Trade Goods", "Common", 3500, 400, 60, True),
    (10940, "Strange Dust", "Trade Goods", "Common", 2800, 500, 20, True),
    (10938, "Lesser Magic Essence", "Trade Goods", "Uncommon", 1700, 260, 80, True),
    (10939, "Greater Magic Essence", "Trade Goods", "Uncommon", 4900, 120, 240, True),
    (10998, "Lesser Astral Essence", "Trade Goods", "Uncommon", 2600, 180, 100, True),
    (11082, "Greater Astral Essence", "Trade Goods", "Uncommon", 7400, 90, 300, True),
    (11134, "Lesser Mystic Essence", "Trade Goods", "Uncommon", 3900, 150, 200, True),
    (11135, "Greater Mystic Essence", "Trade Goods", "Uncommon", 12500, 70, 600, True),
    (11174, "Lesser Nether Essence", "Trade Goods", "Uncommon", 6200, 140, 300, True),
    (11175, "Greater Nether Essence", "Trade Goods", "Uncommon", 17800, 80, 900, True),
    (16202, "Lesser Eternal Essence", "Trade Goods", "Uncommon", 21000, 120, 600, False),
    (16203, "Greater Eternal Essence", "Trade Goods", "Uncommon", 66000, 90, 1800, False),
]
SPIKE = {13452: 1.75, 2453: 1.5}          # price jumps over the last 6 hours
HEATING = {4306: 3.0, 14047: 2.4}         # sales jump, price flat
RESET = 3356                              # bought out and relisted high last hour
CHEAP = {2770: 0.62, 2589: 0.70}          # cheap for the last 2 days -> craft pathways
HOUSES = [(2, "Alliance Auction House", 1.0), (6, "Horde Auction House", 1.06), (7, "Blackwater Auction House", 1.18)]


def generate(db_path: Path, days: int = 30, seed: int = 7) -> None:
    rnd = random.Random(seed)
    if db_path.exists():
        db_path.unlink()
    con = dbmod.connect(db_path)
    end = int(time.time() // 3600 * 3600)
    start = end - days * 24 * 3600
    now = int(time.time())
    con.executemany("INSERT INTO items VALUES (?,?,?,?,?,?,?,?)",
                    [(i, n, None, q, c, v, 1, now) for i, n, c, q, _, _, v, _ in ITEMS])
    rows, snaps = [], []
    for hid, hname, house_mult in HOUSES:
        key = f"r1-h{hid}"
        con.execute("INSERT INTO houses VALUES (?,?,?,?)", (key, 1, hid, hname))
        vol_mult = 1.0 if hid != 7 else 0.35
        for item_id, _, _, _, base, per_day, _, leveling in ITEMS:
            phase = rnd.uniform(0, 2 * math.pi)
            walk = 0.0
            for ts in range(start, end + 1, 3600):
                age = (ts - start) / (end - start)
                hours_left = (end - ts) // 3600
                hour_et = ((ts // 3600) - 5) % 24
                dow = ((ts // 86400) + 4) % 7  # 0 = Monday
                evening = 1 + 0.55 * math.sin((hour_et - 14) / 24 * 2 * math.pi)
                weekly = 1.25 if dow in (1, 5, 6) else 1.0
                walk = walk * 0.97 + rnd.gauss(0, 0.025)
                drift = (1 + 0.25 * (1 - age)) if leveling else (0.9 + 0.2 * age)  # launch curve
                price = base * house_mult * drift * (1 + 0.06 * math.sin(phase + age * 9)) * (1 + walk)
                price *= 1 + 0.04 * (evening - 1)
                demand = per_day * vol_mult / 24 * evening * weekly
                supply = per_day * vol_mult * rnd.uniform(1.6, 2.4)
                if item_id in CHEAP and hours_left < 48:
                    price *= CHEAP[item_id]
                    supply *= 1.7
                if item_id in SPIKE and hours_left < 6:
                    price *= 1 + (SPIKE[item_id] - 1) * (6 - hours_left) / 6
                    demand *= 1.8
                if item_id in HEATING and hours_left < 4:
                    demand *= HEATING[item_id]
                    supply *= 0.8
                if item_id == RESET and hid == 2 and hours_left == 0:
                    price *= 2.3
                    supply *= 0.15
                    demand *= 4
                sold = sum(1 for _ in range(int(demand * 3)) if rnd.random() < 1 / 3) if demand < 400 else int(rnd.gauss(demand, demand ** 0.5))
                cancelled = int(sold * rnd.uniform(0.1, 0.35))
                price = int(max(1, price))
                qty = max(1, int(supply))
                rows.append((key, item_id, ts, int(price * 0.94), price, int(price * 1.18), qty,
                             max(1, qty // max(1, int(rnd.uniform(5, 20)))), max(0, sold), cancelled))
            snaps.append(None)
        for ts in range(start, end + 1, 3600):
            con.execute("INSERT INTO snapshots VALUES (?,?,?,?)", (key, ts, f"sample-{ts}", 0))
    with con:
        con.executemany("INSERT INTO item_hour VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
    con.close()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DATA_DIR / "sample.sqlite"))
    args = ap.parse_args()
    generate(Path(args.db))
    print("Sample data written to", args.db)


if __name__ == "__main__":
    main()
