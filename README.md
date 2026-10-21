# Insight by Milton — v8 (Portfolio CSV Import)

A desktop markets companion for **The Milton Review**, styled after
[themiltonreview.net](https://www.themiltonreview.net).

## What's new in v8

- **Import CSV** on the Portfolio tab — works with broker position exports (Fidelity, Schwab,
  Vanguard, Robinhood, E*TRADE and others) and simple spreadsheets (`Symbol,Shares,Average Cost`).
  Finds the table even below account info, recognises each broker's column names, converts total
  cost basis to cost per share, combines the same stock across accounts, and skips cash, totals and
  options. A preview lets you choose **Add & update** or **Replace all**.
- **Drag & drop** a CSV anywhere on the window to import it.
- **Export CSV** — saves symbol, shares, average cost, price, value, today's change, gain and weight
  (the file can be imported again).
- Holdings without a cost basis are allowed: value and dividends still work, gains appear once you
  add the cost.

## What was new in v7

- **Portfolio** tab — enter shares and average cost; see total value, today's change, total gain,
  an allocation donut (by holding or sector), performance vs the S&P 500 and estimated dividend income.
- **Calendar** tab — earnings and dividend dates for your watchlist and portfolio, Fed rate decisions,
  CPI, the jobs report, GDP, PCE inflation and retail sales, straight from the official schedules.
- **Price alerts** — "Set price alert" on any stock (above / below / % move); Windows notifications
  while the app is open (even minimized), plus an in-app banner. Listed on the Watchlist page.
- **Compare stocks** — up to 5 symbols on one % change chart with key numbers side by side.
- **Search suggestions** — a dropdown of matching stocks as you type in the Markets search.
- **Feedback box** — "Send an idea" (footer) and "Have an idea?" (Home) open a ready-to-send email.
- **Dark mode** — follows Windows on first launch; the sun/moon button in the header switches it.
- **Loading animations** — spinners over charts and pulsing placeholders while content loads.

## What was new in v6

- **Much faster charts** — 1M through 5Y share one cached download, so switching ranges takes about
  0.15 s; MAX dropped from ~5 s to ~0.5 s; volume is drawn as one shape; prices and company details
  download at the same time; a stock starts loading when you hover over it.
- **24 news outlets** — added Business Insider, CBS News MoneyWatch, Fortune, Quartz, Reason,
  Investor's Business Daily, Breitbart News (economy) and The Daily Signal (economy).
- **Quality of life** — remembers window size, position and last page; recent searches on Markets;
  keyboard shortcuts (F1 lists them); sortable watchlist columns; headlines you've opened turn gray;
  the window title shows where you are.

## What was new in v5

- **Chart screenshots** — every chart has a round camera button. It saves a high-resolution PNG or
  JPEG with a caption on the left and the Insight by Milton logo in the bottom-right corner.
  Charts covered: the stock chart, Major Indices, Sector Performance, the Treasury yield curve and
  Recession Watch.
- **Finance-only related news** — a stock's "Related Financial News" now only shows stories about
  markets, earnings, deals, analysts, the economy and similar topics.

## What was new in v4

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
- **Watchlist** — saved symbols with live prices and sparklines, plus your price alerts.
- **Portfolio** — holdings, gains, allocation, performance vs S&P 500, dividend income.
- **Calendar** — earnings, dividends, Fed meetings and economic reports.
- **Bond Market** — Treasury yield curve, spreads and recession signals.

## News sources and political alignment

Ratings are AllSides Media Bias Ratings, checked on allsides.com in October 2026. They describe each
outlet's online news coverage and can change over time.

| Outlet | AllSides rating |
|---|---|
| The Guardian | Left |
| CNBC, The Economist, The New York Times, NPR, Business Insider, CBS News | Lean Left |
| WSJ (news), MarketWatch, Bloomberg, Financial Times, BBC News, Forbes, The Hill, Fortune, Quartz, Reason | Center |
| Fox Business, Washington Examiner, The Washington Times, Investor's Business Daily | Lean Right |
| New York Post, Breitbart News, The Daily Signal | Right |

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
