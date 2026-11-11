# Forever AH Exchange

## Online version (GitHub, no PC needed)
This repository runs itself: every hour, **GitHub Actions** collects the auction house, saves the price history (in the `db` release) and publishes the dashboard to **GitHub Pages**. Updates pushed to `main` go live on the next hourly run.

One-time setup (repo owner):
1. **Settings → Secrets and variables → Actions → Secrets:** add `BLIZZARD_CLIENT_ID` and `BLIZZARD_CLIENT_SECRET`.
2. **Variables:** `HOUSE_IDS` (e.g. `110`), optional `RULESET_NAME` (default `Normal`).
3. **Settings → Pages:** Source = **GitHub Actions**.
4. **Actions → Collect prices and publish dashboard → Run workflow** for the first run.

On the online version, characters and professions are saved in each visitor's own browser.

---

An auction house "stock market" for **WoW: Forever** (US). It collects Blizzard's hourly auction data for the Alliance, Horde and Blackwater houses. From that it estimates sales per hour and shows trends, spikes, flips, hold scores and craft pathways based on your professions.

> **Status:** it's built around the *undocumented* Forever API, using what community developers reported after launch. Everything runs on sample data until you connect your API client. Anything marked `VERIFY` in the code still needs checking against the live API.

## What you need
- Python 3.10+ ([python.org](https://www.python.org/downloads/), tick "Add to PATH" on Windows)
- A free Blizzard API client from https://develop.battle.net/access/clients (any name; redirect URL can be `http://localhost`)

## Setup (about 5 minutes)
```
pip install -r requirements.txt
copy settings.example.env settings.env      (Mac/Linux: cp)
```
Open `settings.env` and paste in your client ID and secret. **Don't share this file.** It's already set to the **PvE** ruleset with the **Alliance** house as the default view; the collector also records Horde and Blackwater in the same ruleset so you can compare prices.

## Try the dashboard right away (sample data)
```
python -m ahtracker.sample_data
python web/app.py
```
Open http://localhost:5000. A yellow banner means you're looking at sample data.

## Connect to the real data, in this order
1. **Probe the API.** This checks which Forever endpoints work and saves their shape:
   ```
   python -m ahtracker.probe --character YourName-YourSurname
   ```
   It writes `data/probe_report.json`, which contains no secrets. Send it to Claude so the code can be adjusted to the real responses.
2. **Collect once:** `python -m ahtracker.collector`
3. **Keep collecting every hour:** `python -m ahtracker.collector --loop`, or double-click `start_collector.bat`.
4. **Dashboard:** `python web/app.py`, or `start_dashboard.bat`. Once real data exists, it switches over automatically.

Sales estimates need at least two snapshots. "Normal for this hour" needs about a week of data, and Long Hold scores need 14 days. Start the collector as early as you can.

## What's on the dashboard
- **Top 5 spikes:** prices furthest above their 7-day average. Sell into these.
- **Heating up:** items selling 1.5× or more their normal rate for this hour while the price is still flat. Buy before the price moves.
- **Best flips:** cheapest listing vs. the 7-day average, after the AH cut.
- **Reset warning:** supply crashed and price jumped in the same hour, which suggests someone bought out the market.
- **Item explorer:** price (market, cheapest, 24h and 7-day averages), sold per hour vs. normal, quantity listed, days of supply, verdict, Hold score, Long Hold reasons, and the same item in the other houses.
- **Craft pathways:** "buy X, smelt/craft Y, list Z" based on each character's skills, ranked by daily gold potential. Recipes you'll unlock within 15 skill points are flagged.
- **Characters and professions:** skills 1–300 that you update as you level. "Sync from Blizzard" pulls them from the character API once it works for Forever.
- **Watchlist and profit calculator.**

## Formulas (copper per unit; 10,000c = 1g)
| | |
|---|---|
| Net sale | sell × (1 − AH cut) |
| Flip profit / ROI | sell × (1 − cut) − buy, then ÷ buy |
| Break-even sell | buy ÷ (1 − cut) |
| Craft profit | makes × product price × (1 − cut) − Σ reagents at **current market price** − expected deposit loss |
| Expected deposit loss | deposit × (1 − sell-through) |
| Daily gold potential | profit per unit × min(market sales per day × 25%, 200) |
| Market price | average price of the cheapest 15% of units listed |
| Velocity | sold this hour ÷ average sold at this hour/weekday over the last 4 weeks |
| Days of supply | quantity listed ÷ sold per day |

**How sales are estimated:** consecutive hourly snapshots are compared. A stack whose quantity dropped counts as a partial buy. A listing that vanished near the cheap end of the market counts as sold. One that vanished from the expensive end, or reappeared slightly cheaper, counts as cancelled or undercut. Listings that vanish with "SHORT" time left are treated as expired.

## Settings to confirm in game
- `AH_CUT_*`: the cut at each house. Classic charged 5% at faction houses and 15% at the neutral one; Forever's Blackwater house may differ.
- `DEPOSIT_RATE`: the deposit as a fraction of vendor price (currently a placeholder).
- `data/recipes.json`: starter recipes from original Classic (smelting, cloth bolts, bandages). Forever may change them. Edit or add your own; the format is simple.

## Known gaps in the Forever API (as of launch week)
- About 40% of items return 404 from the item endpoint, so they show as "Item 12345". The planned in-game addon can export names.
- Character profile lookups reportedly work on US. Whether the professions endpoint works is unconfirmed (the probe tests it), so manual entry stays available.
- There's no historical data source for Forever, so history starts when your collector starts.

## Later
- Hosting for friends on Oracle Cloud's Always Free server (run the same two commands; `python web/app.py --host 0.0.0.0`).
- An in-game addon with bag icons (List / Vendor / Hold) and tooltip prices, fed by a small sync script.
