from ahtracker import db as dbmod
from ahtracker.collector import store_snapshot
from ahtracker.sales import Listing, aggregate, diff, normalize


def L(aid, item, qty, price, tl="LONG"):
    return Listing(aid, item, qty, price, tl)


def test_normalize_item_and_commodity():
    items = normalize([{"id": 1, "item": {"id": 5}, "buyout": 1000, "quantity": 4, "time_left": "LONG"},
                       {"id": 2, "item": {"id": 5}, "bid": 50, "quantity": 1}], commodity=False)
    assert items == [L(1, 5, 4, 250)]  # bid-only dropped, buyout split per unit
    com = normalize([{"id": 3, "item": {"id": 9}, "quantity": 20, "unit_price": 77, "time_left": "SHORT"}], commodity=True)
    assert com == [L(3, 9, 20, 77, "SHORT")]


def test_aggregate_market_is_cheap_end():
    st = aggregate([L(1, 1, 10, 100), L(2, 1, 10, 200), L(3, 1, 80, 1000)])[1]
    assert st["min_price"] == 100 and st["qty"] == 100 and st["listings"] == 3
    assert st["market_price"] == round((10 * 100 + 5 * 200) / 15)
    assert st["median_price"] == 1000


def test_diff_rules():
    prev = {1: L(1, 1, 20, 100), 2: L(2, 1, 5, 105), 3: L(3, 1, 5, 500), 4: L(4, 1, 5, 100, "SHORT"), 5: L(5, 2, 3, 900)}
    curr = {1: L(1, 1, 12, 100),          # partial buy of 8
            6: L(6, 2, 3, 850)}            # #5 reposted cheaper
    # #2 vanished at cheap end -> sold; #3 vanished pricey -> cancelled; #4 SHORT -> expired
    res = diff(prev, curr, {1: 100, 2: 900})
    assert res[1] == {"sold": 13, "cancelled": 5}
    assert res[2] == {"sold": 0, "cancelled": 3}


def test_store_snapshot_roundtrip(tmp_path):
    con = dbmod.connect(tmp_path / "t.sqlite")
    r1 = store_snapshot(con, "h", [L(1, 1, 10, 100), L(2, 1, 10, 120)], 3600)
    assert r1["est_sold_units"] == 0
    assert store_snapshot(con, "h", [L(1, 1, 10, 100), L(2, 1, 10, 120)], 7200)["skipped"]
    r3 = store_snapshot(con, "h", [L(2, 1, 4, 120)], 7200)
    assert r3["ts"] == 7200 and r3["est_sold_units"] == 16
    row = con.execute("SELECT * FROM item_hour WHERE ts=7200").fetchone()
    assert row["est_sold"] == 16 and row["qty"] == 4
