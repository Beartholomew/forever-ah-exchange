"""Hourly collector. Run once:   python -m ahtracker.collector
Run forever:                   python -m ahtracker.collector --loop
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

from . import db as dbmod
from .blizzard import BlizzardClient, BlizzardError
from .config import load_settings
from .sales import Listing, aggregate, diff, normalize

ITEM_LOOKUPS_PER_RUN = 2000


def _hour(ts: float) -> int:
    return int(ts // 3600 * 3600)


def _snapshot_hash(listings: list[Listing]) -> str:
    h = hashlib.sha1()
    for l in sorted(listings, key=lambda l: l.auction_id):
        h.update(f"{l.auction_id}:{l.qty};".encode())
    return h.hexdigest()


def store_snapshot(con: sqlite3.Connection, house_key: str, listings: list[Listing], ts: int) -> dict:
    """Diff against the previous snapshot, write hourly stats. Returns a summary."""
    digest = _snapshot_hash(listings)
    last = con.execute("SELECT data_hash, ts FROM snapshots WHERE house_key=? ORDER BY ts DESC LIMIT 1", (house_key,)).fetchone()
    if last and last["data_hash"] == digest:
        return {"house": house_key, "skipped": "unchanged since last snapshot"}
    if last and ts <= last["ts"]:
        ts = last["ts"] + 3600  # keep one row per hour even if Blizzard's clock lags

    prev = {
        r["auction_id"]: Listing(r["auction_id"], r["item_id"], r["qty"], r["unit_price"], r["time_left"])
        for r in con.execute("SELECT * FROM last_listings WHERE house_key=?", (house_key,))
    }
    prev_market = {}
    if last:
        prev_market = {
            r["item_id"]: r["market_price"]
            for r in con.execute("SELECT item_id, market_price FROM item_hour WHERE house_key=? AND ts=?", (house_key, last["ts"]))
        }
    curr = {l.auction_id: l for l in listings}
    moves = diff(prev, curr, prev_market) if prev else {}
    stats = aggregate(listings)

    rows = []
    for item_id in set(stats) | set(moves):
        st = stats.get(item_id)
        mv = moves.get(item_id, {"sold": 0, "cancelled": 0})
        if st is None:  # sold out completely this hour
            st = {"min_price": None, "market_price": prev_market.get(item_id), "median_price": None, "qty": 0, "listings": 0}
        rows.append((house_key, item_id, ts, st["min_price"], st["market_price"], st["median_price"],
                     st["qty"], st["listings"], mv["sold"], mv["cancelled"]))
    with con:
        con.executemany("INSERT OR REPLACE INTO item_hour VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("DELETE FROM last_listings WHERE house_key=?", (house_key,))
        con.executemany("INSERT INTO last_listings VALUES (?,?,?,?,?,?)",
                        [(house_key, l.auction_id, l.item_id, l.qty, l.unit_price, l.time_left) for l in listings])
        con.execute("INSERT OR REPLACE INTO snapshots VALUES (?,?,?,?)", (house_key, ts, digest, len(listings)))
    return {"house": house_key, "ts": ts, "listings": len(listings), "items": len(stats),
            "est_sold_units": sum(m["sold"] for m in moves.values())}


def icon_url(client: BlizzardClient, item_id: int) -> str | None:
    """Icon image link from the item media endpoint (None if Forever has no media for it)."""
    try:
        media = client.item_media(item_id)
        return next((a["value"] for a in media.get("assets", []) if a.get("key") == "icon"), None)
    except BlizzardError:
        return None


def fill_item_info(con: sqlite3.Connection, client: BlizzardClient, commodity_ids: set[int]) -> int:
    missing = [r[0] for r in con.execute(
        "SELECT DISTINCT item_id FROM item_hour WHERE item_id NOT IN (SELECT item_id FROM items) LIMIT ?",
        (ITEM_LOOKUPS_PER_RUN,))]
    for item_id in missing:
        name = icon = quality = cls = None
        sell = 0
        try:
            js = client.item(item_id)
            name = js.get("name")
            quality = (js.get("quality") or {}).get("name")
            cls = (js.get("item_class") or {}).get("name")
            sell = int(js.get("sell_price") or 0)
            icon = icon_url(client, item_id)
        except BlizzardError as e:
            if e.status != 404:  # ~40% of Forever items 404 at launch; the addon export can fill these later
                raise
        with con:
            con.execute("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?)",
                        (item_id, name, icon, quality, cls, sell, int(item_id in commodity_ids), int(time.time())))
    return len(missing)


def run_once() -> list[dict]:
    s = load_settings()
    client = BlizzardClient(s)
    con = dbmod.connect(s.db_path)
    ruleset = client.pick_ruleset()
    rid = int(ruleset["id"])
    summaries, commodity_ids = [{"ruleset": ruleset.get("name"), "id": rid}], set()
    if not s.house_ids:
        raise SystemExit("Set HOUSE_IDS in settings.env first. Run: python -m ahtracker.find_house")
    houses = [h for h in client.houses(rid) if int(h["id"]) in s.house_ids]
    if not houses:
        raise SystemExit(f"None of HOUSE_IDS {s.house_ids} are in the {ruleset.get('name')} ruleset. Run find_house again.")
    for house in houses:
        hid = int(house["id"])
        key = f"r{rid}-h{hid}"
        label = house.get("name", key).replace(" Auction House", "")
        con.execute("INSERT OR REPLACE INTO houses VALUES (?,?,?,?)", (key, rid, hid, f"{label} AH #{hid}"))
        items_js = client.house_auctions(rid, hid)
        lm = client.last_modified
        listings = normalize(items_js.get("auctions", []), commodity=False)
        try:
            com = normalize(client.house_commodities(rid, hid).get("auctions", []), commodity=True)
            commodity_ids |= {l.item_id for l in com}
            listings += com
        except BlizzardError as e:
            if e.status != 404:
                raise
        ts = _hour(parsedate_to_datetime(lm).timestamp()) if lm else _hour(time.time())
        summaries.append(store_snapshot(con, key, listings, ts))
    con.commit()
    looked_up = fill_item_info(con, client, commodity_ids)
    summaries.append({"item_lookups": looked_up})
    return summaries


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--loop", action="store_true", help="keep running, fetching shortly after each hour")
    args = ap.parse_args()
    while True:
        started = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        try:
            for line in run_once():
                print(started, line)
        except Exception as e:  # keep the loop alive through API hiccups
            print(started, "ERROR", e)
            if not args.loop:
                raise
        if not args.loop:
            break
        now = time.time()
        time.sleep(max(60, _hour(now) + 3600 + 10 * 60 - now))  # ~10 past the next hour


if __name__ == "__main__":
    main()
