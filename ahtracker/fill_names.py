"""Look up every unnamed item (and missing icons) right now instead of waiting for the hourly collector.

    python -m ahtracker.fill_names

Busiest items go first. Items Blizzard has no data for yet (common in Forever) are
remembered so they aren't retried every hour; run with --retry to try those again.
"""
from __future__ import annotations

import argparse
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from . import db as dbmod
from .blizzard import BlizzardClient, BlizzardError
from .collector import icon_url
from .config import load_settings


def lookup(client: BlizzardClient, item_id: int):
    try:
        js = client.item(item_id)
        return (item_id, js.get("name"), icon_url(client, item_id), (js.get("quality") or {}).get("name"),
                (js.get("item_class") or {}).get("name"), int(js.get("sell_price") or 0))
    except BlizzardError as e:
        if e.status == 404:
            return (item_id, None, None, None, None, 0)
        raise


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retry", action="store_true", help="also retry items Blizzard had no data for")
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    s = load_settings()
    client = BlizzardClient(s)
    client.static_namespace()  # resolve once before threading
    client.token()
    con = dbmod.connect(s.db_path)
    where = "i.item_id IS NULL OR i.name IS NULL" if a.retry else "i.item_id IS NULL OR (i.name IS NOT NULL AND i.icon IS NULL)"
    todo = [r[0] for r in con.execute(f"""
        SELECT ih.item_id FROM item_hour ih LEFT JOIN items i ON i.item_id = ih.item_id
        WHERE {where} GROUP BY ih.item_id ORDER BY SUM(ih.qty) DESC""")]
    commodity = {r[0] for r in con.execute("SELECT item_id FROM items WHERE is_commodity=1")}
    print(f"{len(todo):,} items to look up...")
    done = named = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=a.workers) as pool:
        futures = [pool.submit(lookup, client, i) for i in todo]
        for f in as_completed(futures):
            try:
                item_id, name, icon, quality, cls, sell = f.result()
            except Exception as e:  # keep going on odd errors
                print("  skipped one:", e)
                continue
            con.execute("INSERT OR REPLACE INTO items VALUES (?,?,?,?,?,?,?,?)",
                        (item_id, name, icon, quality, cls, sell, int(item_id in commodity), int(time.time())))
            done += 1
            named += name is not None
            if done % 250 == 0:
                con.commit()
                print(f"  {done:,}/{len(todo):,} done, {named:,} named ({time.time() - start:.0f}s)")
    con.commit()
    print(f"Finished: {named:,} of {done:,} items named. "
          f"{done - named:,} have no data from Blizzard yet (Forever's item data is incomplete).")


if __name__ == "__main__":
    main()
