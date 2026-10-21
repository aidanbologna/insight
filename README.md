<p align="center">
  <img src="assets/logo.png" alt="Insight by Milton logo" width="260"/>
</p>

<h1 align="center">Insight by Milton</h1>

<p align="center">
  A desktop markets companion for <a href="https://www.themiltonreview.net"><strong>The Milton Review</strong></a>
  — built with Python, Tkinter and Yahoo Finance.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10%2B-blue?logo=python&logoColor=white" alt="Python 3.10+"/>
  <img src="https://img.shields.io/badge/platform-Windows-0078d4?logo=windows" alt="Windows"/>
  <img src="https://img.shields.io/badge/version-v10-orange" alt="v10"/>
  <img src="https://img.shields.io/badge/license-private-lightgrey" alt="Private"/>
</p>

---

## Overview

Insight by Milton is a native Windows desktop app that puts the whole market on one screen — live
charts, 16+ news outlets, a personal portfolio, price alerts, an economic calendar and the Treasury
yield curve — all styled after the cream-and-terracotta look of themiltonreview.net.

<p align="center">
  <img src="assets/icon.png" alt="App icon" width="96"/>
</p>

---

## Features

| Tab | What you get |
|---|---|
| **Home** | Today's Brief, Market Snapshot, Milton Review articles, Today's Movers, rotating investor quotes |
| **Markets** | Per-stock charts (1D–MAX), moving averages, volume, hover readout, fundamentals, company profile, headlines |
| **News** | 16+ outlets, topic chips, instant filtering, source pages with AllSides bias scale; **FREE / LIMITED / PAYWALL** tags |
| **Watchlist** | Live prices, sparklines, price alerts with Windows notifications |
| **Portfolio** | Holdings, gains, allocation donut, performance vs S&P 500, dividend income, CSV import/export, sell shares |
| **Calendar** | Earnings, dividends, Fed meetings, CPI, jobs report, GDP, PCE, retail sales |
| **Bond Market** | Live Treasury yield curve vs 1 month / 1 year ago, 2s10s & 3M–10Y spread signals, recession watch |

### Search (Ctrl+K)
Find stocks, pages, actions, news outlets, your holdings and watchlist, price alerts, calendar events
and plain-English explanations (P/E, yield curve, ex-dividend date…) — all from one box.

### Dark mode
Follows Windows on first launch; toggle with the sun/moon button in the header.

---

## News sources

Ratings are [AllSides Media Bias Ratings](https://www.allsides.com/media-bias), checked October 2026.

| Outlet | AllSides rating |
|---|---|
| The Guardian | Left |
| CNBC · The Economist · The New York Times · NPR · Business Insider · CBS News | Lean Left |
| WSJ · MarketWatch · Bloomberg · Financial Times · BBC News · Forbes · The Hill · Fortune · Quartz · Reason | Center |
| Fox Business · Washington Examiner · The Washington Times · Investor's Business Daily | Lean Right |
| New York Post · Breitbart News · The Daily Signal | Right |

---

## Quick start

```bash
pip install -r requirements.txt
python insightByMilton.py
```

### Build the Windows app (.exe)

Double-click **`build.bat`**, or run:

```bash
python -m PyInstaller --noconfirm --windowed --name insightByMilton ^
    --icon icon.ico ^
    --add-data "assets;assets" ^
    --add-data "icon.ico;." ^
    insightByMilton.py
```

The app lands in `dist/insightByMilton/insightByMilton.exe`.

---

## Requirements

```
yfinance>=1.0
pandas
numpy
matplotlib
pillow
tzdata
win11toast
tkinterdnd2
```

---

## Version history

Each version below is a commit in this repo's history — browse them on the [Commits](../../commits/master) page.

| Version | Highlights |
|---|---|
| **v1 — Original** | Single Tkinter window, stock chart (yfinance), Treasury yield curve |
| **v2 — Milton Redesign** | Full UI redesign (cream/terracotta), Home, Markets, News, Watchlist, Bond Market pages |
| **v3 — Fundamentals** | Colour-coded fundamental analysis, criteria popup, company profile |
| **v4 — News Sources & Speed** | 16 outlets via RSS, source pages with bias scale, Markets overview, faster charts |
| **v5 — Chart Screenshots** | Camera button on every chart saves a branded PNG/JPEG |
| **v6 — Speed & Quality of Life** | 4× faster chart hover, 24 outlets, remembers window size/position/page, keyboard shortcuts (F1) |
| **v7 — Portfolio, Calendar & Dark Mode** | Portfolio tab, Calendar tab, price alerts, compare stocks, dark mode, loading animations |
| **v8 — Portfolio CSV Import** | Import broker CSVs (Fidelity, Schwab, Vanguard, Robinhood, E\*TRADE), drag & drop, export CSV |
| **v9 — Selling & App Search** | Sell shares, Sales History with realized gains, Ctrl+K universal search |
| **v10 — Paywall Labels & Better Stock News** | FREE / LIMITED / PAYWALL tags on every article, "Free to read only" filter, improved stock headline matching |

---

## Data sources

- **Yahoo Finance** (`yfinance`) — prices, charts, statistics, movers, headlines
- **U.S. Department of the Treasury** — daily par yield curve CSV
- **The Milton Review RSS** — https://www.themiltonreview.net/blog-feed.xml

App data (watchlist, portfolio, settings, price alerts) is stored in `%APPDATA%\InsightByMilton`.

---

## Disclaimer

Educational commentary only — nothing in this app is financial advice. Market data comes from Yahoo
Finance via the unofficial `yfinance` library and may be delayed. Headlines and images belong to
their publishers; the app links to the original articles.

---

<p align="center">
  © 2026 The Milton Review &nbsp;·&nbsp;
  <a href="mailto:aidanbologna@themiltonreview.net">aidanbologna@themiltonreview.net</a> &nbsp;·&nbsp;
  <a href="https://www.themiltonreview.net">themiltonreview.net</a>
</p>
