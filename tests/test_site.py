import json

from ahtracker.build_site import build, compact_series
from ahtracker.sample_data import generate


def test_compact_series_fills_gaps():
    rows = [{"ts": 0, "min_price": 1, "market_price": 2, "qty": 3, "est_sold": 4},
            {"ts": 7200, "min_price": 5, "market_price": 6, "qty": 7, "est_sold": 8}]
    c = compact_series(rows)
    assert c["mkt"] == [2, None, 6] and c["sold"] == [4, None, 8]


def test_build_site(tmp_path):
    db = tmp_path / "s.sqlite"
    generate(db, days=10)
    counts = build(db, tmp_path / "site")
    assert counts and all(n > 0 for n in counts.values())
    meta = json.loads((tmp_path / "site/data/meta.json").read_text())
    key = meta["houses"][0]["house_key"]
    ov = json.loads((tmp_path / f"site/data/overview_{key}.json").read_text())
    assert ov["crafts_all"] and ov["items"]
    item = json.loads((tmp_path / f"site/data/items/{key}/2770.json").read_text())
    assert item["series_c"]["mkt"] and item["other_houses"]
    assert "window.SITE = true" in (tmp_path / "site/index.html").read_text()
