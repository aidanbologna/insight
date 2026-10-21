# Insight by Milton — v3 (Fundamentals)

A desktop markets companion for **The Milton Review**, styled after
[themiltonreview.net](https://www.themiltonreview.net). Version 3 adds colour-coded
**fundamental analysis** for individual stocks.

## Features

- **Home** — "Today's Brief" with market open/closed status and an auto-written market summary,
  a Market Snapshot of 8 key markets with sparklines, Featured Insights from The Milton Review blog
  (RSS), Today's Movers (gainers / losers / most active), newsletter panel and rotating investor quotes.
- **Markets** — search by ticker or company name, interactive chart (1D–MAX) with hover readout,
  50/200-day moving averages and volume, key statistics, company profile, ticker headlines,
  add to watchlist, save chart as PNG/PDF.
- **News** — market headlines by topic or search, beside the latest Milton Review articles.
- **Watchlist** — saved list with live prices, change, day range, volume and 1-month sparkline;
  refreshes every minute.
- **Bond Market** — live U.S. Treasury yield curve vs 1 month / 1 year ago, yields table,
  2s10s and 3M–10Y spread signals with Normal/Inverted badges, and a two-year spread history.
- **Fundamental Analysis (new in v3)** — on the Markets page for individual stocks: 18 metrics in four
  cards (Valuation, Profitability, Growth, Health & Dividends), each colour-coded green / yellow / red
  against fixed rules of thumb, with a good/fair/weak tally, hover tooltips, and a
  "How is each value judged?" popup that explains every metric and its cutoffs.

## How fundamentals are judged

Each value is compared with a fixed, widely used rule of thumb:
**green = good, yellow = fair, red = weak.** Losses and negative values show red; values Yahoo
Finance doesn't report show a gray "—" and aren't counted. The full list of cutoffs is in the
app's "How is each value judged?" popup and in the `FUNDAMENTALS` table near the top of
`insightByMilton.py`, so the thresholds are easy to adjust.

## Run it

```bash
pip install -r requirements.txt
python insightByMilton.py
```

## Build the Windows app (.exe)

Double-click `build.bat`, or run:

```bash
python -m PyInstaller --noconfirm --windowed --name insightByMilton --icon icon.ico --add-data "assets;assets" --add-data "icon.ico;." insightByMilton.py
```

The app is created in `dist/insightByMilton/insightByMilton.exe`.

## Data sources

- Yahoo Finance (`yfinance`) — prices, charts, statistics, fundamentals, movers and headlines
- U.S. Department of the Treasury — daily par yield curve CSV (cached for offline use)
- The Milton Review RSS feed — https://www.themiltonreview.net/blog-feed.xml

The watchlist and Treasury cache are stored in `%APPDATA%/InsightByMilton`.

## Disclaimer

Educational commentary only — nothing in this app is financial advice. Market data comes from
Yahoo Finance via the unofficial `yfinance` library and may be delayed.

© 2026 The Milton Review · aidanbologna@themiltonreview.net · https://www.themiltonreview.net
