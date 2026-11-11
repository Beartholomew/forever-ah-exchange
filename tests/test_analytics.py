from ahtracker import analytics, db as dbmod
from ahtracker.config import Settings
from ahtracker.sample_data import generate


def test_formulas():
    assert analytics.net(100, 0.05) == 95
    assert round(analytics.break_even(95, 0.05)) == 100
    assert round(analytics.flip_roi(100, 200, 0.05), 2) == 0.9


def test_sample_signals(tmp_path):
    path = tmp_path / "s.sqlite"
    generate(path, days=20)
    con = dbmod.connect(path)
    s = Settings()
    stats = analytics.compute_stats(con, "r1-h2")
    tops = analytics.top_lists(stats, s, 0.05)
    names = lambda k: [x["name"] for x in tops[k]]
    assert "Elixir of the Mongoose" in names("spikes")
    # heating = selling fast while the price is flat (sample data shifts with the clock, so check the rule)
    assert all(x["velocity"] >= 1.5 and abs(x["pct_vs7"]) < 0.10 for x in tops["heating"])
    assert names("resets") == ["Kingsblood"]
    paths = analytics.craft_pathways(stats, {"Mining": 70}, s, 0.05)
    assert paths and all(p["profession"] == "Mining" for p in paths)
    assert any(not p["unlocked"] for p in paths) is True  # Smelt Silver at 75 is 'almost unlocked'
    assert stats[2770].long_hold_score is not None
