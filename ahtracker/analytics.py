"""Formulas, signals, Top 5 lists, hold scores and craft pathways.

All prices are copper per unit (10000 copper = 1 gold).

Core formulas
  net sale            = sell × (1 − AH cut)
  flip profit         = sell × (1 − cut) − buy
  break-even sell     = buy ÷ (1 − cut)
  flip ROI            = flip profit ÷ buy   (buy = cheapest listing, sell = 7-day average)
  craft profit        = makes × product price × (1 − cut) − Σ reagent qty × reagent price − expected deposit loss
  expected dep. loss  = deposit × (1 − sell-through)
  daily gold potential= profit per unit × min(units the market buys per day × CAPTURE, MAX_UNITS)
Reagents are priced at what they'd sell for now (opportunity cost), not what you paid.
"""
from __future__ import annotations

import json
import math
import sqlite3
from dataclasses import asdict, dataclass, field

from .config import DATA_DIR, Settings

H = 3600
DAY = 24 * H
CAPTURE = 0.25   # assume you can take ~25% of an item's daily sales
MAX_UNITS = 200  # and never plan on more than this per day


def net(price: float, cut: float) -> float:
    return price * (1 - cut)


def break_even(buy: float, cut: float) -> float:
    return buy / (1 - cut)


def flip_roi(buy: float, sell: float, cut: float) -> float:
    return (net(sell, cut) - buy) / buy if buy else 0.0


@dataclass
class ItemStats:
    item_id: int
    name: str | None
    icon: str | None
    quality: str | None
    item_class: str | None
    vendor_sell: int
    price: int | None          # current market price
    min_price: int | None
    prev_price: int | None
    qty: int
    prev_qty: int
    listings: int
    ma7: float | None
    ma30: float | None
    sd7: float | None
    ma72h: float | None
    ma14d: float | None
    sold_last_hour: int
    sold_per_hour_normal: float
    daily_sold: float
    sold7: int
    cancelled7: int
    days_of_history: float
    qty_recent: float | None
    qty_older: float | None
    daily_sold_cv: float | None
    # derived
    pct_1h: float | None = None
    pct_vs7: float | None = None      # vs 'normal' = 7-day average (launch economy moves fast)
    pct_vs30: float | None = None
    velocity: float | None = None
    days_supply: float | None = None
    z7: float | None = None
    trend: float | None = None
    flip_roi: float | None = None
    sell_through: float = 0.5
    verdict: str = "Hold"
    hold_score: int = 50
    long_hold_score: int | None = None
    long_hold_reasons: list[str] = field(default_factory=list)
    reset_flag: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


STATS_SQL = """
WITH last AS (SELECT MAX(ts) AS t FROM item_hour WHERE house_key = :h)
SELECT ih.item_id,
  i.name, i.icon, i.quality, i.item_class, COALESCE(i.vendor_sell, 0) AS vendor_sell,
  MAX(CASE WHEN ih.ts = last.t THEN ih.market_price END) AS price,
  MAX(CASE WHEN ih.ts = last.t THEN ih.min_price END) AS min_price,
  MAX(CASE WHEN ih.ts = last.t - 3600 THEN ih.market_price END) AS prev_price,
  COALESCE(MAX(CASE WHEN ih.ts = last.t THEN ih.qty END), 0) AS qty,
  COALESCE(MAX(CASE WHEN ih.ts = last.t - 3600 THEN ih.qty END), 0) AS prev_qty,
  COALESCE(MAX(CASE WHEN ih.ts = last.t THEN ih.listings END), 0) AS listings,
  AVG(CASE WHEN ih.ts > last.t - 7*86400 THEN ih.market_price END) AS ma7,
  AVG(ih.market_price) AS ma30,
  AVG(CASE WHEN ih.ts > last.t - 7*86400 THEN ih.market_price * 1.0 * ih.market_price END) AS sq7,
  AVG(CASE WHEN ih.ts > last.t - 72*3600 THEN ih.market_price END) AS ma72h,
  AVG(CASE WHEN ih.ts > last.t - 14*86400 THEN ih.market_price END) AS ma14d,
  COALESCE(MAX(CASE WHEN ih.ts = last.t THEN ih.est_sold END), 0) AS sold_last_hour,
  AVG(CASE WHEN ih.ts > last.t - 28*86400 AND ih.ts < last.t AND ((ih.ts / 3600) % 168) = ((last.t / 3600) % 168)
           THEN ih.est_sold END) AS sold_same_hour,
  SUM(CASE WHEN ih.ts > last.t - 7*86400 THEN ih.est_sold ELSE 0 END) AS sold7,
  SUM(CASE WHEN ih.ts > last.t - 7*86400 THEN ih.est_cancelled ELSE 0 END) AS cancelled7,
  (last.t - MIN(ih.ts)) / 86400.0 AS days_of_history,
  AVG(CASE WHEN ih.ts > last.t - 3*86400 THEN ih.qty END) AS qty_recent,
  AVG(CASE WHEN ih.ts <= last.t - 3*86400 AND ih.ts > last.t - 14*86400 THEN ih.qty END) AS qty_older
FROM item_hour ih CROSS JOIN last
LEFT JOIN items i ON i.item_id = ih.item_id
WHERE ih.house_key = :h AND ih.ts > last.t - 30*86400
GROUP BY ih.item_id
"""

DAILY_SQL = """
SELECT item_id, ts / 86400 AS d, SUM(est_sold) AS s FROM item_hour
WHERE house_key = :h AND ts > (SELECT MAX(ts) FROM item_hour WHERE house_key = :h) - 14*86400
GROUP BY item_id, d
"""


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def compute_stats(con: sqlite3.Connection, house_key: str, item_ids: list[int] | None = None) -> dict[int, ItemStats]:
    daily: dict[int, list[float]] = {}
    for r in con.execute(DAILY_SQL, {"h": house_key}):
        daily.setdefault(r["item_id"], []).append(r["s"])
    out = {}
    sql = STATS_SQL
    params: dict = {"h": house_key}
    if item_ids:
        sql = sql.replace("WHERE ih.house_key = :h", f"WHERE ih.house_key = :h AND ih.item_id IN ({','.join(str(int(i)) for i in item_ids)})")
    for r in con.execute(sql, params):
        d = dict(r)
        sq = d.pop("sq7")
        same_hour = d.pop("sold_same_hour")
        ma7 = d["ma7"]
        sd = math.sqrt(max(0.0, sq - ma7 * ma7)) if ma7 is not None and sq is not None else None
        hist_days = max(d["days_of_history"], 1 / 24)
        sold7 = d["sold7"] or 0
        hourly_avg = sold7 / min(7 * 24, max(1, hist_days * 24))
        days = daily.get(d["item_id"], [])
        cv = None
        if len(days) >= 3:
            m = sum(days) / len(days)
            cv = (math.sqrt(sum((x - m) ** 2 for x in days) / len(days)) / m) if m else None
        st = ItemStats(**d, sd7=sd,
                       sold_per_hour_normal=same_hour if same_hour is not None else hourly_avg,
                       daily_sold=hourly_avg * 24, daily_sold_cv=cv)
        derive(st)
        out[st.item_id] = st
    return out


def derive(st: ItemStats) -> None:
    p = st.price
    if p and st.prev_price:
        st.pct_1h = p / st.prev_price - 1
    if p and st.ma7:
        st.pct_vs7 = p / st.ma7 - 1
    if p and st.ma30:
        st.pct_vs30 = p / st.ma30 - 1
    if st.sold_per_hour_normal and st.sold_per_hour_normal > 0:
        st.velocity = st.sold_last_hour / st.sold_per_hour_normal
    if st.daily_sold > 0:
        st.days_supply = st.qty / st.daily_sold
    if p and st.ma7 and st.sd7:
        st.z7 = (p - st.ma7) / st.sd7 if st.sd7 > 0 else 0.0
    if st.ma72h and st.ma14d:
        st.trend = st.ma72h / st.ma14d - 1
    if st.sold7 + st.cancelled7 > 0:
        st.sell_through = st.sold7 / (st.sold7 + st.cancelled7)
    st.reset_flag = bool(st.prev_qty and st.prev_price and p and st.qty < 0.4 * st.prev_qty and p > 1.5 * st.prev_price)

    # Short-term verdict and Hold score (0-100, higher = better time to own it)
    z, trend = st.z7 or 0.0, st.trend or 0.0
    if st.reset_flag:
        st.verdict = "Avoid: possible reset"
    elif z <= -1 and trend >= -0.03:
        st.verdict = "Buy"
    elif z <= -1:
        st.verdict = "Wait: still falling"
    elif z >= 1:
        st.verdict = "Sell now"
    else:
        st.verdict = "Hold"
    st.hold_score = round(_clamp(50 - z * 15 + trend * 100 + ((st.velocity or 1) - 1) * 10, 0, 100))

    # Long Hold score: needs two weeks of history
    if st.days_of_history < 14:
        st.long_hold_score = None
        st.long_hold_reasons = [f"Needs 14+ days of history ({st.days_of_history:.1f} so far)"]
        return
    score, why = 50.0, []
    if st.qty_recent is not None and st.qty_older:
        supply = st.qty_recent / st.qty_older - 1
        score -= _clamp(supply * 60, -25, 25)
        why.append(f"Supply {'shrinking' if supply < 0 else 'growing'} {abs(supply):.0%} vs last 2 weeks")
    if st.daily_sold_cv is not None:
        steady = st.daily_sold_cv < 0.5
        score += 10 if steady else -10
        why.append("Sells steadily every day" if steady else "Sales are bursty")
    if st.pct_vs30 is not None:
        score -= _clamp(st.pct_vs30 * 50, -15, 15)
        why.append(f"Price {abs(st.pct_vs30):.0%} {'below' if st.pct_vs30 < 0 else 'above'} its 30-day average")
    if trend < -0.05:
        score -= 10
        why.append("Drifting down (typical for leveling mats as players reach 60)")
    st.long_hold_score = round(_clamp(score, 0, 100))
    st.long_hold_reasons = why


def passes_filters(st: ItemStats, s: Settings) -> bool:
    return (st.price or 0) >= s.min_price_copper and st.daily_sold >= s.min_daily_sold and st.listings >= s.min_listings


MIN_HOURS = {"spikes": 24, "flips": 24, "resets": 24, "heating": 48}


def top_lists(stats: dict[int, ItemStats], s: Settings, cut: float, n: int = 5) -> dict:
    """Top 5 lists. Each list waits until there's enough history to compare against,
    and skips items Blizzard hasn't given a name yet (you can't act on 'Item 12345')."""
    hours = max((st.days_of_history for st in stats.values()), default=0) * 24 + 1
    pool = [st for st in stats.values() if passes_filters(st, s) and st.name]
    for st in pool:
        if st.min_price and st.ma7:
            st.flip_roi = flip_roi(st.min_price, st.ma7, cut)
    ready = {k: hours >= h for k, h in MIN_HOURS.items()}
    spikes = sorted((st for st in pool if (st.pct_vs7 or 0) > 0.15 and not st.reset_flag), key=lambda st: st.pct_vs7, reverse=True)[:n]
    heating = sorted((st for st in pool if (st.velocity or 0) >= 1.5 and abs(st.pct_vs7 or 0) < 0.10 and not st.reset_flag),
                     key=lambda st: st.velocity, reverse=True)[:n]
    flips = sorted((st for st in pool if (st.flip_roi or 0) > 0.10 and not st.reset_flag and st.listings >= 5),
                   key=lambda st: st.flip_roi, reverse=True)[:n]
    resets = [st for st in stats.values() if st.reset_flag and st.name and (st.prev_qty or 0) >= 10][:n]
    lists = {"spikes": spikes, "heating": heating, "flips": flips, "resets": resets}
    out = {k: ([x.to_dict() for x in v] if ready[k] else []) for k, v in lists.items()}
    out["history_hours"] = round(hours)
    out["needs_hours"] = MIN_HOURS
    return out


# ---------------- craft pathways ----------------

def load_recipes() -> list[dict]:
    return json.loads((DATA_DIR / "recipes.json").read_text(encoding="utf-8"))["recipes"]


def _name(stats: dict[int, ItemStats], item_id: int) -> str:
    st = stats.get(item_id)
    return (st.name if st and st.name else f"Item {item_id}")


def craft_pathways(stats: dict[int, ItemStats], professions: dict[str, int], s: Settings, cut: float,
                   recipes: list[dict] | None = None, near: int = 15) -> list[dict]:
    """Rank recipes by daily gold potential for a character's professions.
    professions: {"Mining": 185, ...}. Includes recipes up to `near` skill points away as 'almost unlocked'."""
    recipes = recipes if recipes is not None else load_recipes()
    known = {r["product"]: r for r in recipes if professions.get(r["profession"], -1) >= r["skill"]}

    def unit_cost(item_id: int, depth: int = 0) -> tuple[float | None, list[str]]:
        """Cheapest way to get one unit: buy it, or craft it from cheaper parts you can make."""
        st = stats.get(item_id)
        buy = st.price if st and st.price else None
        r = known.get(item_id)
        if r and depth < 2:
            total, steps = 0.0, []
            for rid, q in r["reagents"].items():
                c, sub = unit_cost(int(rid), depth + 1)
                if c is None:
                    total = None
                    break
                total += c * q
                steps += sub
            if total is not None:
                per = total / r["makes"]
                if buy is None or per < buy:
                    return per, steps + [f"{r['name']} ({_name(stats, item_id)})"]
        return buy, ([f"Buy {_name(stats, item_id)}"] if buy else [])

    out = []
    for r in recipes:
        skill = professions.get(r["profession"])
        if skill is None or skill < r["skill"] - near:
            continue
        product = stats.get(r["product"])
        if not product or not product.price:
            continue
        cost, steps, cheap = 0.0, [], []
        ok = True
        for rid, q in r["reagents"].items():
            c, sub = unit_cost(int(rid))
            if c is None:
                ok = False
                break
            cost += c * q
            steps += [f"{x} ×{q}" if x.startswith("Buy") else x for x in sub]
            mst = stats.get(int(rid))
            if mst and mst.pct_vs7 is not None and mst.pct_vs7 <= -0.15:
                cheap.append(f"{_name(stats, int(rid))} is {abs(mst.pct_vs7):.0%} below its 7-day average")
        if not ok:
            continue
        deposit = (product.vendor_sell or 0) * s.deposit_rate
        dep_loss = deposit * (1 - product.sell_through)
        revenue = net(product.price, cut) * r["makes"]
        profit = revenue - cost - dep_loss * r["makes"]
        per_unit = profit / r["makes"]
        units_day = min(product.daily_sold * CAPTURE, MAX_UNITS)
        out.append({
            "recipe": r["name"], "profession": r["profession"], "skill_needed": r["skill"],
            "unlocked": skill >= r["skill"], "product_id": r["product"], "product": _name(stats, r["product"]),
            "product_quality": product.quality, "product_icon": product.icon,
            "makes": r["makes"], "reagent_cost": round(cost), "sell_price": product.price,
            "profit_per_craft": round(profit), "margin": profit / cost if cost else None,
            "market_sells_per_day": round(product.daily_sold, 1), "daily_gold_potential": round(per_unit * units_day),
            "steps": steps + [f"{r['name']} → list {_name(stats, r['product'])} at ~{product.price / 10000:.2f}g"],
            "why": cheap, "verdict": product.verdict,
        })
    out.sort(key=lambda x: (x["unlocked"], x["daily_gold_potential"]), reverse=True)
    return out
