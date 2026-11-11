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
    path = load_settings().db_path
    con = sqlite3.connect(str(path))
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
