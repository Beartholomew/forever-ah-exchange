"""Keep the database small enough to store for free.

    python -m ahtracker.prune [--days 60] [--vacuum]
"""
from __future__ import annotations

import argparse
import sqlite3

from .config import load_settings


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=60)
    ap.add_argument("--vacuum", action="store_true")
    a = ap.parse_args()
    settings = load_settings()
    con = sqlite3.connect(str(settings.db_path))
    if settings.house_ids:  # drop houses you no longer collect
        keep = ",".join(str(i) for i in settings.house_ids)
        old = [r[0] for r in con.execute(f"SELECT house_key FROM houses WHERE house_id NOT IN ({keep})")]
        for key in old:
            for table in ("item_hour", "last_listings", "snapshots", "houses"):
                con.execute(f"DELETE FROM {table} WHERE house_key=?", (key,))
        if old:
            con.commit()
            print("Removed houses no longer collected:", ", ".join(old))
    last = con.execute("SELECT MAX(ts) FROM item_hour").fetchone()[0]
    if last:
        n = con.execute("DELETE FROM item_hour WHERE ts < ?", (last - a.days * 86400,)).rowcount
        con.execute("DELETE FROM snapshots WHERE ts < ?", (last - a.days * 86400,))
        con.commit()
        print(f"Removed {n:,} rows older than {a.days} days")
    con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    con.execute("PRAGMA journal_mode=DELETE")
    if a.vacuum:
        con.execute("VACUUM")
    con.close()


if __name__ == "__main__":
    main()
