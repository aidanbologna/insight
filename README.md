# Insight by Milton — v2 (Milton Redesign)

A desktop markets companion for **The Milton Review**, redesigned to match the look of
[themiltonreview.net](https://www.themiltonreview.net): cream background, serif headlines and the
terracotta accent.

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

- Yahoo Finance (`yfinance`) — prices, charts, statistics, movers and headlines
- U.S. Department of the Treasury — daily par yield curve CSV (cached for offline use)
- The Milton Review RSS feed — https://www.themiltonreview.net/blog-feed.xml

The watchlist and Treasury cache are stored in `%APPDATA%/InsightByMilton`.

## Disclaimer

Educational commentary only — nothing in this app is financial advice. Market data comes from
Yahoo Finance via the unofficial `yfinance` library and may be delayed.

© 2026 The Milton Review · aidanbologna@themiltonreview.net · https://www.themiltonreview.net
