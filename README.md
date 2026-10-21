# Insight by Milton — v4 (News Sources & Speed)

A desktop markets companion for **The Milton Review**, styled after
[themiltonreview.net](https://www.themiltonreview.net).

## What's new in v4

- **Faster** — the window opens ~1.5 s sooner (heavy libraries load in the background), chart hovering
  is ~4× faster (only the crosshair is redrawn), thumbnails are shrunk off the UI thread, and news
  filtering happens instantly in memory.
- **News from 16 outlets** — headlines come straight from each publisher's RSS feed and open directly
  on the publisher's website. Filter by topic or keyword instantly.
- **Source pages** — click any outlet for a summary, key facts, a Left → Right political alignment
  scale (AllSides Media Bias Rating) and its top stories with images.
- **Markets overview** — the Markets tab now opens on the whole market: major index cards and a
  comparison chart, S&P 500 sector performance and the largest companies. Click anything for its full
  detail view; "← Market overview" or the Markets tab returns to the overview.
- Stock headlines on the detail view now come from the 16 outlets instead of Yahoo Finance.

## Features

- **Home** — Today's Brief, Market Snapshot, Featured Insights from The Milton Review, Today's Movers,
  newsletter panel and rotating quotes.
- **Markets** — market overview, plus per-stock charts (1D–MAX, moving averages, volume, hover readout),
  key statistics, colour-coded fundamental analysis with a criteria popup, company profile and headlines.
- **News** — 16 outlets, topic chips, instant filtering, source pages with bias scale.
- **Watchlist** — saved symbols with live prices and sparklines.
- **Bond Market** — Treasury yield curve, spreads and recession signals.

## News sources and political alignment

Ratings are AllSides Media Bias Ratings, checked on allsides.com in October 2026. They describe each
outlet's online news coverage and can change over time.

| Outlet | AllSides rating |
|---|---|
| The Guardian | Left |
| CNBC, The Economist, The New York Times, NPR | Lean Left |
| The Wall Street Journal (news), MarketWatch, Bloomberg, Financial Times, BBC News, Forbes, The Hill | Center |
| Fox Business, Washington Examiner, The Washington Times | Lean Right |
| New York Post | Right |

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

## Disclaimer

Educational commentary only — nothing in this app is financial advice. Market data comes from Yahoo
Finance via the unofficial `yfinance` library and may be delayed. Headlines and images belong to their
publishers; the app links to the original articles.

© 2026 The Milton Review · aidanbologna@themiltonreview.net · https://www.themiltonreview.net
