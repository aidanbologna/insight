# Insight by Milton — v1 (Original)

The first prototype of Insight by Milton: a single Tkinter window that charts a stock's 2026 closing
prices and the U.S. Treasury yield curve.

## Features

- Stock price chart (default AAPL) with a search box, using `yfinance`
- "Bond Market" button that draws the Treasury yield curve and prints recession signals to the console
- Live date/time clock, logo header and navigation buttons (Home, News and Watchlist were placeholders)

## Run it

```bash
pip install -r requirements.txt
python insightByMilton.py
```

## Known limitations

- Asset paths and the Treasury CSV path are hard-coded to `C:/Users/Owner/OneDrive/Desktop/...`,
  so the script only runs on the original computer without editing those paths.
- The Treasury download line is commented out; it reads a CSV saved on the Desktop.
- Network calls run on the UI thread, so the window freezes while loading.

## Disclaimer

Educational commentary only — nothing in this app is financial advice. Market data comes from
Yahoo Finance via the unofficial `yfinance` library and may be delayed.

© 2026 The Milton Review · aidanbologna@themiltonreview.net · https://www.themiltonreview.net
