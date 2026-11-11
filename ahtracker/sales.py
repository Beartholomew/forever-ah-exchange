"""Turn raw auction listings into hourly price stats and estimated sales.

Blizzard doesn't report sales, so we compare consecutive snapshots:
  * a listing whose quantity dropped  -> partial purchase (sold the difference)
  * a listing that vanished early      -> sold if it was at the cheap end of the
                                          market, cancelled if it was pricey or
                                          reappeared slightly cheaper (undercut repost)
  * a listing that vanished while SHORT -> probably expired, ignored
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True)
class Listing:
    auction_id: int
    item_id: int
    qty: int
    unit_price: int  # copper per unit (buyout)
    time_left: str


def normalize(auctions: list[dict], commodity: bool) -> list[Listing]:
    out = []
    for a in auctions or []:
        item = a.get("item") or {}
        item_id = item.get("id")
        qty = int(a.get("quantity") or 1)
        if commodity:
            unit = a.get("unit_price")
        else:
            buyout = a.get("buyout")
            unit = (int(buyout) // max(qty, 1)) if buyout else None
        if not item_id or not unit:
            continue  # bid-only auctions have no buyout price to use
        out.append(Listing(int(a["id"]), int(item_id), qty, int(unit), str(a.get("time_left", ""))))
    return out


MARKET_SHARE = 0.15  # market price = average of the cheapest 15% of units listed


def aggregate(listings: list[Listing]) -> dict[int, dict]:
    by_item: dict[int, list[Listing]] = defaultdict(list)
    for l in listings:
        by_item[l.item_id].append(l)
    stats = {}
    for item_id, ls in by_item.items():
        ls.sort(key=lambda l: l.unit_price)
        total = sum(l.qty for l in ls)
        target = max(1, round(total * MARKET_SHARE))
        taken = cost = 0
        for l in ls:
            take = min(l.qty, target - taken)
            cost += take * l.unit_price
            taken += take
            if taken >= target:
                break
        half, run, median = total / 2, 0, ls[-1].unit_price
        for l in ls:
            run += l.qty
            if run >= half:
                median = l.unit_price
                break
        stats[item_id] = {
            "min_price": ls[0].unit_price,
            "market_price": round(cost / taken),
            "median_price": median,
            "qty": total,
            "listings": len(ls),
        }
    return stats


CHEAP_END = 1.10  # vanished listings priced within 10% of market count as sales


def diff(prev: dict[int, Listing], curr: dict[int, Listing], prev_market: dict[int, int]) -> dict[int, dict]:
    """Return {item_id: {"sold": n, "cancelled": n}} between two snapshots."""
    res: dict[int, dict] = defaultdict(lambda: {"sold": 0, "cancelled": 0})
    new_by_item: dict[int, list[Listing]] = defaultdict(list)
    for aid, l in curr.items():
        if aid not in prev:
            new_by_item[l.item_id].append(l)

    for aid, old in prev.items():
        now = curr.get(aid)
        if now is not None:
            if now.qty < old.qty:
                res[old.item_id]["sold"] += old.qty - now.qty
            continue
        if old.time_left.upper() == "SHORT":
            continue  # likely expired
        # undercut repost: same item and quantity relisted cheaper
        repost = next((n for n in new_by_item[old.item_id] if n.qty == old.qty and n.unit_price < old.unit_price), None)
        if repost is not None:
            new_by_item[old.item_id].remove(repost)
            res[old.item_id]["cancelled"] += old.qty
            continue
        market = prev_market.get(old.item_id) or old.unit_price
        if old.unit_price <= market * CHEAP_END:
            res[old.item_id]["sold"] += old.qty
        else:
            res[old.item_id]["cancelled"] += old.qty
    return dict(res)
