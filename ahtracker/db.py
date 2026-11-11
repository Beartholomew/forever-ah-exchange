"""SQLite storage. One row per item per house per hour keeps it small enough for free hosting."""
from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS houses (
    house_key TEXT PRIMARY KEY,      -- e.g. "r1-h2"
    ruleset_id INTEGER, house_id INTEGER, name TEXT
);
CREATE TABLE IF NOT EXISTS items (
    item_id INTEGER PRIMARY KEY,
    name TEXT, icon TEXT, quality TEXT, item_class TEXT,
    vendor_sell INTEGER, is_commodity INTEGER DEFAULT 0, updated INTEGER
);
CREATE TABLE IF NOT EXISTS snapshots (
    house_key TEXT, ts INTEGER, data_hash TEXT, n_auctions INTEGER,
    PRIMARY KEY (house_key, ts)
);
CREATE TABLE IF NOT EXISTS item_hour (
    house_key TEXT, item_id INTEGER, ts INTEGER,
    min_price INTEGER,      -- copper per unit, cheapest buyout
    market_price INTEGER,   -- copper per unit, avg of cheapest 15% of quantity
    median_price INTEGER,
    qty INTEGER, listings INTEGER,
    est_sold INTEGER DEFAULT 0, est_cancelled INTEGER DEFAULT 0,
    PRIMARY KEY (house_key, item_id, ts)
);
CREATE INDEX IF NOT EXISTS ix_item_hour_ts ON item_hour (house_key, ts);
CREATE TABLE IF NOT EXISTS last_listings (
    house_key TEXT, auction_id INTEGER, item_id INTEGER,
    qty INTEGER, unit_price INTEGER, time_left TEXT,
    PRIMARY KEY (house_key, auction_id)
);
"""


def connect(path: Path | str) -> sqlite3.Connection:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con
