# =============================================================================
#  Insight by Milton
#  A desktop markets companion for The Milton Review (themiltonreview.net)
#
#  Pages:  Home · Markets · News · Watchlist · Bond Market
#  Data:   Yahoo Finance (yfinance), U.S. Treasury, The Milton Review RSS feed
# =============================================================================

import html
import io
import json
import os
import queue
import random
import re
import sys
import threading
import webbrowser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from urllib import request

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog

import numpy as np
import pandas as pd
import yfinance as yf
from PIL import Image, ImageOps, ImageTk

import matplotlib
matplotlib.use("TkAgg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.dates import DateFormatter
from matplotlib.ticker import FuncFormatter, MaxNLocator

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:  # tzdata missing — fall back to local time
    EASTERN = None


# -----------------------------------------------------------------------------
# 1. Brand: colours, links and copy borrowed from themiltonreview.net
# -----------------------------------------------------------------------------
BG = "#FDFBF7"           # page cream
SURFACE = "#FFFFFF"      # cards
SAND = "#F3EFE7"         # newsletter band / soft fills
BORDER = "#E6E0D6"       # hairlines
INK = "#1C1C1C"          # text
MUTED = "#595959"        # secondary text
FAINT = "#8C877F"        # tertiary text
ACCENT = "#D47A5D"       # Milton terracotta
ACCENT_DARK = "#B9603F"
ACCENT_SOFT = "#F7E6DF"
UP = "#2F7D4F"
UP_SOFT = "#E4F0E7"
DOWN = "#B4473A"
DOWN_SOFT = "#F6E2DE"
FAIR = "#A0721A"         # amber "yellow" that stays readable on cream
FAIR_SOFT = "#F8EDD3"
RATING_STYLE = {          # rating -> (text colour, pill colour, word)
    "good": (UP, UP_SOFT, "Good"),
    "fair": (FAIR, FAIR_SOFT, "Fair"),
    "weak": (DOWN, DOWN_SOFT, "Weak"),
    None: (FAINT, SAND, "Not rated"),
}

APP_NAME = "Insight by Milton"
SITE_URL = "https://www.themiltonreview.net"
BLOG_URL = SITE_URL + "/blog"
RSS_URL = SITE_URL + "/blog-feed.xml"
CONTACT_EMAIL = "aidanbologna@themiltonreview.net"

QUOTES = [
    ("Investing without research is like playing stud poker and never looking at the cards.", "Peter Lynch"),
    ("An investment in knowledge pays the best interest.", "Benjamin Franklin"),
    ("The stock market is filled with individuals who know the price of everything, but the value of nothing.", "Phillip Fisher"),
    ("One can predict the course of a comet more easily than one can predict the course of Citigroup's stock.", "Jim Simons"),
    ("Investing should be more like watching paint dry or watching grass grow. If you want excitement, take $800 and go to Las Vegas.", "Paul Samuelson"),
    ("He who controls the spice controls the universe.", "Frank Herbert"),
    ("My investment advice is rooted in my understanding of economics.", "Peter Schiff"),
    ("The ultimate purpose of economics, of course, is to understand and promote the enhancement of well-being.", "Ben Bernanke"),
    ("The curious task of economics is to demonstrate to men how little they really know about what they imagine they can design.", "F.A. Hayek"),
    ("Economics is everywhere, and understanding economics can help you make better decisions and lead a happier life.", "Tyler Cowen"),
]

# Home page "Market Snapshot" cards: (label, Yahoo symbol, how to format it)
SNAPSHOT = [
    ("S&P 500", "^GSPC", "index"),
    ("Dow Jones", "^DJI", "index"),
    ("Nasdaq", "^IXIC", "index"),
    ("Russell 2000", "^RUT", "index"),
    ("10-Yr Treasury", "^TNX", "yield"),
    ("Gold", "GC=F", "usd"),
    ("Crude Oil", "CL=F", "usd"),
    ("Bitcoin", "BTC-USD", "usd"),
]

DEFAULT_WATCHLIST = [
    {"symbol": "AAPL", "name": "Apple Inc."},
    {"symbol": "MSFT", "name": "Microsoft Corporation"},
    {"symbol": "NVDA", "name": "NVIDIA Corporation"},
    {"symbol": "AMZN", "name": "Amazon.com, Inc."},
    {"symbol": "GOOGL", "name": "Alphabet Inc."},
    {"symbol": "SPY", "name": "SPDR S&P 500 ETF Trust"},
]

# Markets chart ranges: label -> (period to download, bar interval, days to show)
# Daily ranges download extra history so the 50/200-day averages are valid
# from the very first bar on screen.
RANGES = {
    "1D": ("1d", "5m", None),
    "5D": ("5d", "30m", None),
    "1M": ("2y", "1d", 30),
    "6M": ("2y", "1d", 182),
    "YTD": ("2y", "1d", "ytd"),
    "1Y": ("2y", "1d", 365),
    "5Y": ("10y", "1d", 365 * 5),
    "MAX": ("max", "1d", None),
}
RANGE_WORDS = {"1D": "today", "5D": "past 5 days", "1M": "past month", "6M": "past 6 months",
               "YTD": "year to date", "1Y": "past year", "5Y": "past 5 years", "MAX": "all time"}

# Fundamental analysis: every metric, how it's shown and how it's judged.
#   key       Yahoo Finance field (a tuple means "first one that exists")
#   fmt       x = multiple, ratio = plain number, pct = percentage, money = dollars
#   better    "lower" or "higher" is better
#   cuts      (a, b) band boundaries.  lower is better:  good < a <= fair <= b < weak
#                                      higher is better: weak < a <= fair <= b < good
#   negative  red label shown when the value is below zero
#   zero      gray label shown (and not rated) when the value is exactly zero
FUNDAMENTALS = [
    ("Valuation", [
        {"name": "P/E (TTM)", "key": "trailingPE", "fmt": "x", "better": "lower", "cuts": (15, 25),
         "negative": "Loss", "loss_eps": "trailingEps",
         "about": "Share price divided by the last 12 months of earnings per share — how many dollars "
                  "investors pay for each $1 of profit."},
        {"name": "Forward P/E", "key": "forwardPE", "fmt": "x", "better": "lower", "cuts": (15, 25),
         "negative": "Loss", "loss_eps": "forwardEps",
         "about": "Like P/E, but using analysts' expected earnings for the next 12 months."},
        {"name": "PEG ratio", "key": ("trailingPegRatio", "pegRatio"), "fmt": "ratio", "better": "lower",
         "cuts": (1, 2), "negative": "Negative",
         "about": "P/E divided by the expected earnings growth rate. It adjusts the P/E for how fast "
                  "profits are growing; around 1 is often considered fairly priced."},
        {"name": "Price / Book", "key": "priceToBook", "fmt": "x", "better": "lower", "cuts": (3, 5),
         "negative": "Negative",
         "about": "Share price divided by book value per share (assets minus liabilities). Asset-light "
                  "companies like software firms naturally run high."},
        {"name": "Price / Sales", "key": "priceToSalesTrailing12Months", "fmt": "x", "better": "lower",
         "cuts": (2, 5),
         "about": "Market value divided by the last 12 months of revenue. Useful for companies with "
                  "little or no profit yet."},
        {"name": "EV / EBITDA", "key": "enterpriseToEbitda", "fmt": "x", "better": "lower", "cuts": (10, 15),
         "negative": "Negative",
         "about": "Enterprise value (market value plus debt minus cash) divided by earnings before interest, "
                  "taxes, depreciation and amortization. Compares companies however they're financed."},
    ]),
    ("Profitability", [
        {"name": "Gross margin", "key": "grossMargins", "fmt": "pct", "better": "higher", "cuts": (0.20, 0.40),
         "about": "Share of revenue left after the direct cost of making the product or service."},
        {"name": "Operating margin", "key": "operatingMargins", "fmt": "pct", "better": "higher",
         "cuts": (0.05, 0.15),
         "about": "Share of revenue left after all day-to-day costs such as wages, research and marketing."},
        {"name": "Profit margin", "key": "profitMargins", "fmt": "pct", "better": "higher", "cuts": (0.05, 0.10),
         "about": "Share of revenue that ends up as net profit after every expense, interest payment and tax."},
        {"name": "Return on equity", "key": "returnOnEquity", "fmt": "pct", "better": "higher",
         "cuts": (0.08, 0.15),
         "about": "Net profit divided by shareholders' equity — how well the company turns owners' money "
                  "into profit. Heavy debt or buybacks can push it unusually high."},
        {"name": "Return on assets", "key": "returnOnAssets", "fmt": "pct", "better": "higher",
         "cuts": (0.02, 0.05),
         "about": "Net profit divided by everything the company owns — how productive its assets are."},
    ]),
    ("Growth", [
        {"name": "Revenue growth", "key": "revenueGrowth", "fmt": "pct", "better": "higher", "cuts": (0, 0.10),
         "about": "Change in the latest quarter's revenue compared with the same quarter a year earlier."},
        {"name": "Earnings growth", "key": "earningsGrowth", "fmt": "pct", "better": "higher", "cuts": (0, 0.10),
         "about": "Change in the latest quarter's earnings compared with the same quarter a year earlier."},
    ]),
    ("Health & Dividends", [
        {"name": "Debt / Equity", "key": "debtToEquity", "scale": 0.01, "fmt": "ratio", "better": "lower",
         "cuts": (0.5, 1.5), "negative": "Negative",
         "about": "Total debt divided by shareholders' equity. Higher means the company leans more on "
                  "borrowed money. Negative means liabilities exceed assets."},
        {"name": "Current ratio", "key": "currentRatio", "fmt": "ratio", "better": "higher", "cuts": (1, 1.5),
         "about": "Assets that turn into cash within a year divided by bills due within a year. Below 1 "
                  "means short-term bills exceed short-term resources."},
        {"name": "Quick ratio", "key": "quickRatio", "fmt": "ratio", "better": "higher", "cuts": (0.5, 1),
         "about": "Like the current ratio but leaves out inventory, counting only the most liquid assets."},
        {"name": "Free cash flow", "key": "freeCashflow", "fmt": "money", "better": "higher", "cuts": (0, 0),
         "about": "Cash from operations minus spending on equipment and buildings over the last 12 months — "
                  "money left over for dividends, buybacks or paying down debt."},
        {"name": "Payout ratio", "key": "payoutRatio", "fmt": "pct", "better": "lower", "cuts": (0.60, 0.90),
         "zero": "No dividend",
         "about": "Share of profit paid out as dividends. Very high payouts can be hard to keep up. "
                  "Companies that pay no dividend aren't rated."},
    ]),
]

# Treasury par yield curve maturities: (short label, CSV column)
MATURITIES = [("1M", "1 Mo"), ("3M", "3 Mo"), ("6M", "6 Mo"), ("1Y", "1 Yr"), ("2Y", "2 Yr"),
              ("3Y", "3 Yr"), ("5Y", "5 Yr"), ("7Y", "7 Yr"), ("10Y", "10 Yr"), ("20Y", "20 Yr"),
              ("30Y", "30 Yr")]
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value={year}&page&_format=csv")


# -----------------------------------------------------------------------------
# 2. Paths — work both as a script and as a PyInstaller EXE
# -----------------------------------------------------------------------------
def resource_path(*parts):
    """Find a bundled file (assets/…) next to the script or inside the EXE."""
    bases = [getattr(sys, "_MEIPASS", None),
             os.path.dirname(os.path.abspath(sys.argv[0])),
             os.path.dirname(os.path.abspath(__file__))]
    for base in bases:
        if base and os.path.exists(os.path.join(base, *parts)):
            return os.path.join(base, *parts)
    return os.path.join(bases[-1], *parts)


DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "InsightByMilton")
os.makedirs(DATA_DIR, exist_ok=True)
WATCHLIST_FILE = os.path.join(DATA_DIR, "watchlist.json")
TREASURY_CACHE = os.path.join(DATA_DIR, "treasury_cache.csv")


# -----------------------------------------------------------------------------
# 3. Formatting helpers
# -----------------------------------------------------------------------------
SCALE = 1.0      # set from the screen DPI once the window exists
FONTS = {}       # named fonts, filled in by init_fonts()


def S(px):
    """Scale a pixel size for high-DPI screens."""
    return int(round(px * SCALE))


def is_missing(v):
    return v is None or (isinstance(v, float) and np.isnan(v))


def fmt_price(v):
    if is_missing(v):
        return "—"
    return f"{v:,.4f}" if abs(v) < 1 else f"{v:,.2f}"


def fmt_big(v):
    if is_missing(v):
        return "—"
    for size, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= size:
            return f"{v / size:,.2f}{suffix}"
    return f"{v:,.0f}"


def fmt_pct(v):
    return "—" if is_missing(v) else f"{v:+.2f}%"


def fmt_change(v):
    return "—" if is_missing(v) else f"{v:+,.2f}"


def trend_color(v):
    if is_missing(v) or abs(v) < 1e-9:
        return MUTED
    return UP if v > 0 else DOWN


def time_ago(dt):
    if dt is None:
        return ""
    now = datetime.now(dt.tzinfo) if dt.tzinfo else datetime.now()
    secs = max(0, (now - dt).total_seconds())
    if secs < 3600:
        return f"{int(secs // 60) or 1}m ago"
    if secs < 86400:
        return f"{int(secs // 3600)}h ago"
    if secs < 86400 * 7:
        return f"{int(secs // 86400)}d ago"
    return dt.strftime("%b %d").replace(" 0", " ")


def short_date(dt):
    return dt.strftime("%b %d, %Y").replace(" 0", " ") if dt else ""


def clock_time(dt, seconds=False):
    return dt.strftime("%I:%M:%S %p" if seconds else "%I:%M %p").lstrip("0")


def now_eastern():
    return datetime.now(EASTERN) if EASTERN else datetime.now()


def market_status():
    """(is_open, description) for the NYSE regular session. Holidays aren't tracked."""
    now = now_eastern()
    open_t = now.replace(hour=9, minute=30, second=0, microsecond=0)
    close_t = now.replace(hour=16, minute=0, second=0, microsecond=0)
    if now.weekday() < 5 and open_t <= now < close_t:
        mins = int((close_t - now).total_seconds() // 60)
        return True, f"U.S. markets open · closes in {mins // 60}h {mins % 60:02d}m"
    nxt = open_t if (now.weekday() < 5 and now < open_t) else open_t + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    when = "today" if nxt.date() == now.date() else nxt.strftime("%A")
    return False, f"U.S. markets closed · opens {when} 9:30 AM ET"


def fmt_metric(v, fmt, cutoff=False):
    if fmt == "pct":
        return f"{v * 100:g}%" if cutoff else f"{v * 100:.1f}%"
    if fmt == "money":
        return ("-$" if v < 0 else "$") + fmt_big(abs(v))
    if fmt == "x":
        return f"{v:g}" if cutoff else f"{v:,.1f}"
    return f"{v:g}" if cutoff else f"{v:,.2f}"


def judge_metric(spec, info):
    """Return (rating, display text). rating is good / fair / weak, or None when it isn't rated."""
    keys = spec["key"] if isinstance(spec["key"], tuple) else (spec["key"],)
    v = next((info.get(k) for k in keys if not is_missing(info.get(k))), None)
    if v is None:
        eps = info.get(spec.get("loss_eps", ""))
        if isinstance(eps, (int, float)) and eps < 0:
            return "weak", spec.get("negative", "Loss")   # Yahoo leaves P/E blank for loss-makers
        return None, "—"
    v = float(v) * spec.get("scale", 1)
    if v == 0 and "zero" in spec:
        return None, spec["zero"]
    if v < 0 and "negative" in spec:
        return "weak", spec["negative"]
    a, b = spec["cuts"]
    if spec["better"] == "lower":
        rating = "good" if v < a else "fair" if v <= b else "weak"
    else:
        rating = "good" if v > b else "fair" if v >= a else "weak"
    return rating, fmt_metric(v, spec["fmt"])


def describe_cutoffs(spec):
    """[(rating, rule text)] used by the criteria popup and the hover tooltips."""
    a, b = (fmt_metric(c, spec["fmt"], cutoff=True) for c in spec["cuts"])
    if spec["cuts"][0] == spec["cuts"][1]:
        return [("good", "Positive"), ("weak", "Negative")]
    if spec["better"] == "lower":
        rules = [("good", f"Below {a}"), ("fair", f"{a} – {b}"), ("weak", f"Above {b}")]
    else:
        rules = [("good", f"Above {b}"), ("fair", f"{a} – {b}"), ("weak", f"Below {a}")]
    if "negative" in spec:
        rules[-1] = ("weak", rules[-1][1] + f" or {spec['negative'].lower()}")
    return rules


# -----------------------------------------------------------------------------
# 4. Data layer — every function here is slow and runs on a background thread
# -----------------------------------------------------------------------------
YF_LOCK = threading.Lock()   # yf.download() isn't thread safe
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InsightByMilton/2.0"}
TICKER_RE = re.compile(r"^[\^A-Z0-9.\-=]{1,12}$")


def http_get(url, timeout=15):
    req = request.Request(url, headers=HTTP_HEADERS)
    with request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_image(url):
    return Image.open(io.BytesIO(http_get(url))).convert("RGB")


def fetch_images(urls):
    """Download many thumbnails in parallel. Failed downloads come back as None."""
    def one(url):
        try:
            return fetch_image(url) if url else None
        except Exception:
            return None
    with ThreadPoolExecutor(max_workers=6) as pool:
        return list(pool.map(one, urls))


def fetch_milton_articles(limit=12):
    """Latest posts from The Milton Review's RSS feed."""
    root = ET.fromstring(http_get(RSS_URL))
    ns = {"dc": "http://purl.org/dc/elements/1.1/"}
    articles = []
    for item in root.iter("item"):
        try:
            date = parsedate_to_datetime(item.findtext("pubDate"))
        except Exception:
            date = None
        summary = html.unescape(re.sub(r"<[^>]+>", "", item.findtext("description") or ""))
        enclosure = item.find("enclosure")
        articles.append({
            "title": (item.findtext("title") or "").strip(),
            "link": item.findtext("link"),
            "summary": re.sub(r"\s+", " ", summary).strip(),
            "date": date,
            "image": enclosure.get("url") if enclosure is not None else None,
            "author": item.findtext("dc:creator", default="The Milton Review", namespaces=ns),
        })
    return articles[:limit]


def fetch_headlines(query, count=12):
    """Market headlines from Yahoo Finance search."""
    items = yf.Search(query, max_results=1, news_count=count).news or []
    out = []
    for n in items:
        sizes = (n.get("thumbnail") or {}).get("resolutions") or []
        small = [r for r in sizes if r.get("tag") == "140x140"] or sizes
        ts = n.get("providerPublishTime")
        out.append({
            "title": n.get("title", ""),
            "publisher": n.get("publisher", ""),
            "link": n.get("link"),
            "date": datetime.fromtimestamp(ts) if ts else None,
            "image": small[0].get("url") if small else None,
        })
    return out


def fetch_quotes(symbols):
    """Last price, day change and a 1-month sparkline for each symbol (one request)."""
    if not symbols:
        return {}
    with YF_LOCK:
        df = yf.download(symbols, period="1mo", interval="1d", group_by="ticker",
                         auto_adjust=True, progress=False, threads=True)
    quotes = {}
    for sym in symbols:
        try:
            sub = df[sym] if isinstance(df.columns, pd.MultiIndex) else df
            sub = sub.dropna(subset=["Close"])
        except KeyError:
            continue
        if sub.empty:
            continue
        close = sub["Close"]
        last = float(close.iloc[-1])
        prev = float(close.iloc[-2]) if len(close) > 1 else last
        quotes[sym] = {
            "last": last, "prev": prev, "change": last - prev,
            "pct": (last / prev - 1) * 100 if prev else 0.0,
            "high": float(sub["High"].iloc[-1]), "low": float(sub["Low"].iloc[-1]),
            "volume": float(sub["Volume"].iloc[-1]),
            "spark": [float(v) for v in close.tail(22)],
        }
    return quotes


def fetch_movers(kind, count=8):
    """Today's gainers / losers / most active from Yahoo's predefined screeners."""
    result = yf.screen(kind, count=count)
    return [{
        "symbol": q.get("symbol"),
        "name": q.get("shortName") or q.get("longName") or "",
        "price": q.get("regularMarketPrice"),
        "pct": q.get("regularMarketChangePercent"),
    } for q in result.get("quotes", []) if q.get("symbol")]


def search_symbol(query):
    """Turn a company name like 'apple' into a ticker like 'AAPL'."""
    for item in yf.Search(query, max_results=6, news_count=0).quotes or []:
        if item.get("symbol"):
            return item["symbol"], item.get("shortname") or item.get("longname") or ""
    raise LookupError(f"Couldn't find a match for “{query}”.")


def fetch_history(symbol, range_key):
    fetch_period, interval, span = RANGES[range_key]
    try:
        hist = yf.Ticker(symbol).history(period=fetch_period, interval=interval, auto_adjust=True)
    except Exception:
        return pd.DataFrame()
    if hist.empty:
        return hist
    hist = hist[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
    if interval == "1d":
        hist["MA50"] = hist["Close"].rolling(50).mean()
        hist["MA200"] = hist["Close"].rolling(200).mean()
        last = hist.index[-1]
        if span == "ytd":
            start = last.replace(month=1, day=1, hour=0, minute=0, second=0)
            hist = hist[hist.index >= start]
        elif span:
            hist = hist[hist.index >= last - pd.Timedelta(days=span)]
    return hist


def fetch_info(symbol):
    t = yf.Ticker(symbol)
    try:
        info = dict(t.info or {})
    except Exception:
        info = {}
    if is_missing(info.get("regularMarketPrice")) or is_missing(info.get("regularMarketPreviousClose")):
        try:
            fast = t.fast_info
            info.setdefault("regularMarketPrice", fast.last_price)
            info.setdefault("regularMarketPreviousClose", fast.previous_close)
        except Exception:
            pass
    return info


def load_symbol(query, range_key):
    """Everything the Markets page needs for one symbol."""
    symbol = query.strip().upper()
    hist = fetch_history(symbol, range_key) if TICKER_RE.match(symbol) else pd.DataFrame()
    if hist.empty:
        symbol, _ = search_symbol(query)
        hist = fetch_history(symbol, range_key)
    if hist.empty:
        raise LookupError(f"No price data found for “{query}”.")
    info = fetch_info(symbol)
    try:
        news = fetch_headlines(symbol, count=5)
    except Exception:
        news = []
    return {"symbol": symbol, "hist": hist, "info": info, "news": news}


def fetch_treasury():
    """Daily Treasury par yield curve for this year and last year, cached on disk."""
    frames = []
    this_year = datetime.now().year
    for year in (this_year - 1, this_year):
        for _attempt in range(2):
            try:
                text = http_get(TREASURY_URL.format(year=year), timeout=20).decode("utf-8")
                frames.append(pd.read_csv(io.StringIO(text)))
                break
            except Exception:
                continue
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df.to_csv(TREASURY_CACHE, index=False)
    elif os.path.exists(TREASURY_CACHE):
        df = pd.read_csv(TREASURY_CACHE)
    else:
        raise ConnectionError("Couldn't reach treasury.gov and no saved copy exists yet.")
    df["Date"] = pd.to_datetime(df["Date"])
    return df.drop_duplicates("Date").sort_values("Date").reset_index(drop=True)


# -----------------------------------------------------------------------------
# 5. Background worker — runs slow calls off the UI thread
# -----------------------------------------------------------------------------
class Worker:
    """Runs a function on a thread, then calls back on the Tk thread with its result."""

    def __init__(self, root):
        self.root = root
        self.results = queue.Queue()
        self._poll()

    def run(self, fn, on_done=None, on_error=None):
        def job():
            try:
                self.results.put((on_done, fn(), None))
            except Exception as exc:
                self.results.put((on_error, None, exc))
        threading.Thread(target=job, daemon=True).start()

    def _poll(self):
        while True:
            try:
                callback, result, error = self.results.get_nowait()
            except queue.Empty:
                break
            try:
                if error is not None:
                    if callback:
                        callback(error)
                    else:
                        print(f"Background task failed: {error}")
                elif callback:
                    callback(result)
            except tk.TclError:
                pass  # the widget was destroyed while we were waiting
            except Exception as exc:
                print(f"Callback failed: {exc}")
        self.root.after(50, self._poll)


class WatchlistStore:
    """Saves the watchlist to %APPDATA%/InsightByMilton/watchlist.json."""

    def __init__(self):
        try:
            with open(WATCHLIST_FILE, "r", encoding="utf-8") as f:
                self.items = json.load(f)
        except (OSError, ValueError):
            self.items = [dict(i) for i in DEFAULT_WATCHLIST]
        self.listeners = []

    @property
    def symbols(self):
        return [i["symbol"] for i in self.items]

    def __contains__(self, symbol):
        return symbol in self.symbols

    def add(self, symbol, name=""):
        if symbol not in self:
            self.items.append({"symbol": symbol, "name": name})
            self._save()

    def remove(self, symbol):
        self.items = [i for i in self.items if i["symbol"] != symbol]
        self._save()

    def _save(self):
        try:
            with open(WATCHLIST_FILE, "w", encoding="utf-8") as f:
                json.dump(self.items, f, indent=2)
        except OSError as exc:
            print(f"Couldn't save watchlist: {exc}")
        for listener in self.listeners:
            listener()


# -----------------------------------------------------------------------------
# 6. Styling: fonts, ttk theme, matplotlib theme
# -----------------------------------------------------------------------------
def load_bundled_fonts():
    """Optional: drop Caudex (or any .ttf) into assets/fonts to match the website exactly."""
    folder = resource_path("assets", "fonts")
    if sys.platform != "win32" or not os.path.isdir(folder):
        return
    import ctypes
    for name in os.listdir(folder):
        if name.lower().endswith((".ttf", ".otf")):
            ctypes.windll.gdi32.AddFontResourceExW(os.path.join(folder, name), 0x10, 0)


def init_fonts(root):
    families = set(tkfont.families(root))

    def pick(*names):
        return next((n for n in names if n in families), "TkDefaultFont")

    serif = pick("Caudex", "Georgia", "Cambria", "Times New Roman")
    sans = pick("Segoe UI", "Helvetica", "Arial")
    light = pick("Segoe UI Light", sans)
    semi = pick("Segoe UI Semibold", sans)
    spec = {
        "hero": (serif, 46, "bold"),
        "display": (light, 26),
        "page_title": (serif, 30, "bold"),
        "h2": (serif, 17, "bold"),
        "card_title": (semi, 13),
        "lead": (sans, 12),
        "body": (sans, 10),
        "body_semi": (semi, 10),
        "small": (sans, 9),
        "small_semi": (semi, 9),
        "eyebrow": (semi, 8),
        "nav": (sans, 10),
        "nav_active": (sans, 10, "underline"),
        "button": (sans, 10),
        "chip": (sans, 9),
        "price": (serif, 32, "bold"),
        "card_value": (serif, 17, "bold"),
        "quote": (light, 20),
        "brand": (serif, 12, "bold"),
    }
    for key, (family, size, *style) in spec.items():
        FONTS[key] = tkfont.Font(root, family=family, size=size,
                                 weight="bold" if "bold" in style else "normal",
                                 underline="underline" in style)
    matplotlib.rcParams.update({
        "font.family": [sans, "DejaVu Sans"],
        "font.size": 9,
        "axes.edgecolor": BORDER,
        "axes.labelcolor": MUTED,
        "xtick.color": MUTED,
        "ytick.color": MUTED,
        "text.color": INK,
    })


def init_ttk(root):
    style = ttk.Style(root)
    style.theme_use("clam")
    style.layout("Milton.Vertical.TScrollbar", [
        ("Vertical.Scrollbar.trough", {"sticky": "ns", "children": [
            ("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
    style.configure("Milton.Vertical.TScrollbar", troughcolor=BG, background=BORDER,
                    bordercolor=BG, lightcolor=BORDER, darkcolor=BORDER, gripcount=0,
                    arrowsize=S(9), relief="flat")
    style.map("Milton.Vertical.TScrollbar", background=[("active", FAINT)])


def style_axes(ax, price_on_right=False):
    ax.set_facecolor(BG)
    for side in ("top", "left", "right", "bottom"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_visible(True)
    ax.spines["bottom"].set_color(BORDER)
    ax.tick_params(colors=MUTED, labelsize=8, length=0, pad=6)
    ax.grid(True, axis="y", color=BORDER, linewidth=0.8)
    ax.set_axisbelow(True)
    if price_on_right:
        ax.yaxis.tick_right()


# -----------------------------------------------------------------------------
# 7. Reusable widgets
# -----------------------------------------------------------------------------
def round_rect(canvas, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return canvas.create_polygon(pts, smooth=True, **kw)


def label(parent, text="", font="body", fg=INK, bg=None, **kw):
    return tk.Label(parent, text=text, font=FONTS[font], fg=fg, bg=bg or parent.cget("bg"), **kw)


def wrap_label(parent, text="", font="body", fg=INK, **kw):
    """A left-aligned label that re-wraps its text whenever it is resized."""
    lbl = label(parent, text, font, fg, justify="left", anchor="w", **kw)

    def rewrap(e):
        width = max(e.width - 4, 50)
        if abs(width - int(lbl.cget("wraplength") or 0)) > 2:  # ignore jitter so layouts settle
            lbl.configure(wraplength=width)
    lbl.bind("<Configure>", rewrap)
    return lbl


def divider(parent, pady=0):
    line = tk.Frame(parent, bg=BORDER, height=1)
    line.pack(fill="x", pady=pady)
    return line


def card(parent, bg=SURFACE, border=True):
    return tk.Frame(parent, bg=bg, highlightthickness=1 if border else 0,
                    highlightbackground=BORDER, highlightcolor=BORDER)


def descendants(widget):
    yield widget
    for child in widget.winfo_children():
        yield from descendants(child)


def make_clickable(widget, command):
    for w in descendants(widget):
        if isinstance(w, RoundButton):
            continue
        w.bind("<Button-1>", lambda e: command(), add="+")
        try:
            w.configure(cursor="hand2")
        except tk.TclError:
            pass


def add_hover(widget, on_enter, on_leave):
    """Enter/leave for a whole widget tree, ignoring moves between its own children."""
    def leave(_e):
        x, y = widget.winfo_pointerxy()
        under = widget.winfo_containing(x, y)
        if under is not None and (under is widget or str(under).startswith(str(widget) + ".")):
            return
        on_leave()
    for w in descendants(widget):
        w.bind("<Enter>", lambda e: on_enter(), add="+")
        w.bind("<Leave>", leave, add="+")


def hover_border(frame):
    add_hover(frame, lambda: frame.configure(highlightbackground=ACCENT),
              lambda: frame.configure(highlightbackground=BORDER))


def set_bg(widget, color):
    for w in descendants(widget):
        if getattr(w, "keep_bg", False):
            continue
        try:
            w.configure(bg=color)
        except tk.TclError:
            pass


def open_link(url):
    if url:
        webbrowser.open(url)


class RoundButton(tk.Canvas):
    """Pill-shaped button like the 'Subscribe' button on the website."""
    STYLES = {  # fill, text, hover fill, outline
        "primary": (ACCENT, BG, ACCENT_DARK, None),
        "dark": (INK, BG, "#3A3A3A", None),
        "ghost": (None, INK, SAND, INK),
        "chip": (SAND, INK, BORDER, None),
        "chip_on": (INK, BG, INK, None),
    }

    def __init__(self, parent, text, command=None, kind="primary", font="button",
                 padx=20, pady=9, radius=10):
        self.parent_bg = parent.cget("bg")
        self.font = FONTS[font]
        self.text, self.command, self.kind = text, command, kind
        self.padx, self.pady, self.radius = S(padx), S(pady), S(radius)
        self.hover = False
        w, h = self._size()
        super().__init__(parent, width=w, height=h, bg=self.parent_bg, highlightthickness=0,
                         bd=0, cursor="hand2")
        self.keep_bg = True
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _size(self):
        return (self.font.measure(self.text) + 2 * self.padx,
                self.font.metrics("linespace") + 2 * self.pady)

    def _draw(self):
        self.delete("all")
        w, h = self._size()
        fill, fg, hover, outline = self.STYLES[self.kind]
        color = hover if self.hover else fill
        color = color or self.parent_bg
        round_rect(self, 1, 1, w - 2, h - 2, self.radius, fill=color, outline=outline or color)
        self.create_text(w / 2, h / 2, text=self.text, fill=fg, font=self.font)

    def _set_hover(self, value):
        self.hover = value
        self._draw()

    def _click(self, event):
        if self.command and 0 <= event.x <= self.winfo_width() and 0 <= event.y <= self.winfo_height():
            self.command()

    def update_button(self, text=None, kind=None):
        if text is not None:
            self.text = text
        if kind is not None:
            self.kind = kind
        w, h = self._size()
        self.configure(width=w, height=h)
        self._draw()


class ChipGroup(tk.Frame):
    """A row of pill toggles. Single-choice by default, multi-choice with multi=True."""

    def __init__(self, parent, options, command=None, value=None, multi=False):
        super().__init__(parent, bg=parent.cget("bg"))
        self.command, self.multi = command, multi
        self.selected = set(value or []) if multi else value
        self.buttons = {}
        for opt in options:
            b = RoundButton(self, opt, command=lambda o=opt: self._click(o), kind="chip",
                            font="chip", padx=12, pady=5, radius=12)
            b.pack(side="left", padx=(0, S(6)))
            self.buttons[opt] = b
        self._refresh()

    def _click(self, option):
        if self.multi:
            self.selected ^= {option}
        else:
            self.selected = option
        self._refresh()
        if self.command:
            self.command(self.selected)

    def set(self, value):
        self.selected = value
        self._refresh()

    def _refresh(self):
        for opt, b in self.buttons.items():
            on = opt in self.selected if self.multi else opt == self.selected
            b.update_button(kind="chip_on" if on else "chip")


class SearchEntry(tk.Frame):
    """Text box with a placeholder and a terracotta focus ring."""

    def __init__(self, parent, placeholder, on_submit=None, width=26):
        super().__init__(parent, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        self.placeholder = placeholder
        self.entry = tk.Entry(self, relief="flat", bd=0, bg=SURFACE, fg=FAINT, insertbackground=INK,
                              font=FONTS["body"], width=width)
        self.entry.pack(fill="both", expand=True, padx=S(12), pady=S(8))
        self.entry.insert(0, placeholder)
        self.showing_placeholder = True
        self.entry.bind("<FocusIn>", self._focus_in)
        self.entry.bind("<FocusOut>", self._focus_out)
        if on_submit:
            self.entry.bind("<Return>", lambda e: on_submit())

    def _focus_in(self, _e):
        self.configure(highlightbackground=ACCENT)
        if self.showing_placeholder:
            self.entry.delete(0, "end")
            self.entry.configure(fg=INK)
            self.showing_placeholder = False

    def _focus_out(self, _e):
        self.configure(highlightbackground=BORDER)
        if not self.entry.get():
            self.entry.insert(0, self.placeholder)
            self.entry.configure(fg=FAINT)
            self.showing_placeholder = True

    def get(self):
        text = self.entry.get().strip()
        if self.showing_placeholder:
            text = text.replace(self.placeholder, "", 1).strip()
        return text

    def clear(self):
        self.entry.delete(0, "end")
        if self.focus_get() is not self.entry:
            self._focus_out(None)

    def focus(self):
        self.entry.focus_set()


class ScrollFrame(tk.Frame):
    """A vertically scrolling page. Put content in .inner."""

    def __init__(self, parent, bg=BG):
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0, yscrollincrement=S(24))
        self.bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                 style="Milton.Vertical.TScrollbar")
        self.inner = tk.Frame(self.canvas, bg=bg)
        self.window = self.canvas.create_window(0, 0, window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=self.bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self.window, width=e.width))

    def scroll(self, event):
        if self.inner.winfo_height() <= self.canvas.winfo_height():
            return
        self.canvas.yview_scroll(-3 if event.delta > 0 else 3, "units")

    def to_top(self):
        self.canvas.yview_moveto(0)


class Sparkline(tk.Canvas):
    """Tiny trend line drawn straight onto a Tk canvas (much lighter than matplotlib)."""

    def __init__(self, parent, height=38, width=None):
        super().__init__(parent, height=S(height), bg=parent.cget("bg"), highlightthickness=0, bd=0)
        if width:
            self.configure(width=S(width))
        self.values, self.color = [], INK
        self.bind("<Configure>", lambda e: self._draw())

    def set(self, values, color):
        self.values, self.color = list(values), color
        self._draw()

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or len(self.values) < 2:
            return
        pad = S(3)
        lo, hi = min(self.values), max(self.values)
        span = (hi - lo) or 1
        step = (w - 2 * pad) / (len(self.values) - 1)
        pts = []
        for i, v in enumerate(self.values):
            pts += [pad + i * step, pad + (hi - v) * (h - 2 * pad) / span]
        base = pad + (hi - self.values[0]) * (h - 2 * pad) / span
        self.create_line(pad, base, w - pad, base, fill=BORDER, dash=(2, 3))
        self.create_line(*pts, fill=self.color, width=S(1.6), capstyle="round", joinstyle="round")
        self.create_oval(pts[-2] - S(2.5), pts[-1] - S(2.5), pts[-2] + S(2.5), pts[-1] + S(2.5),
                         fill=self.color, outline="")


class Thumbnail(tk.Frame):
    """Fixed-height image slot that crops its picture to fit whatever width it gets."""

    def __init__(self, parent, height, width=None, bg=SAND, placeholder=""):
        super().__init__(parent, bg=bg, height=S(height))
        if width:
            self.configure(width=S(width))
        self.pack_propagate(False)
        self.keep_bg = True
        self.image_label = tk.Label(self, bg=bg, bd=0, text=placeholder[:1].upper(),
                                    font=FONTS["h2"], fg=FAINT)
        self.image_label.keep_bg = True
        self.image_label.pack(fill="both", expand=True)
        self.source, self.photo, self.rendered_size = None, None, None
        self.bind("<Configure>", lambda e: self._render())

    def set_image(self, pil_image):
        self.source = pil_image
        self._render()

    def _render(self):
        if self.source is None:
            return
        size = (self.winfo_width(), self.winfo_height())
        if size[0] < 10 or size == self.rendered_size:
            return
        self.rendered_size = size
        self.photo = ImageTk.PhotoImage(ImageOps.fit(self.source, size, Image.LANCZOS))
        self.image_label.configure(image=self.photo)


def section_header(parent, title, right_text=None, right_command=None, pady=(S(44), S(16))):
    row = tk.Frame(parent, bg=parent.cget("bg"))
    row.pack(fill="x", pady=pady)
    label(row, title, "display").pack(side="left", anchor="s")
    side = None
    if right_text:
        side = label(row, right_text, "body", fg=ACCENT if right_command else FAINT)
        side.pack(side="right", anchor="s", pady=(0, S(6)))
        if right_command:
            make_clickable(side, right_command)
    return row, side


def change_pill(parent, pct, font="small_semi", width=0):
    color = trend_color(pct)
    soft = UP_SOFT if color == UP else DOWN_SOFT if color == DOWN else SAND
    pill = label(parent, fmt_pct(pct), font, fg=color, bg=soft, padx=S(8), pady=S(2), width=width)
    pill.keep_bg = True
    return pill


class Tooltip:
    """Small dark hint that appears after hovering a widget (and its children) briefly."""

    def __init__(self, widget, text):
        self.widget, self.text = widget, text
        self.tip, self.job = None, None
        add_hover(widget, self._schedule, self._hide)
        for w in descendants(widget):
            w.bind("<ButtonPress>", lambda e: self._hide(), add="+")

    def _schedule(self):
        if self.job is None and self.tip is None:
            self.job = self.widget.after(350, self._show)

    def _show(self):
        self.job = None
        x, y = self.widget.winfo_pointerxy()
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.attributes("-topmost", True)
        label(self.tip, self.text, "small", fg=BG, bg=INK, justify="left", wraplength=S(320),
              padx=S(12), pady=S(8)).pack()
        self.tip.wm_geometry(f"+{x + S(14)}+{y + S(16)}")

    def _hide(self):
        if self.job:
            self.widget.after_cancel(self.job)
            self.job = None
        if self.tip:
            self.tip.destroy()
            self.tip = None


def rating_pill(parent, rating, text, width=10):
    fg, soft, _ = RATING_STYLE[rating]
    pill = label(parent, text, "small_semi", fg=fg, bg=soft, padx=S(8), pady=S(2), width=width)
    pill.keep_bg = True
    return pill


def rating_legend(parent):
    box = tk.Frame(parent, bg=parent.cget("bg"))
    for rating in ("good", "fair", "weak"):
        fg, _, word = RATING_STYLE[rating]
        dot = tk.Canvas(box, width=S(9), height=S(9), bg=box.cget("bg"), highlightthickness=0)
        dot.create_oval(1, 1, S(8), S(8), fill=fg, outline="")
        dot.pack(side="left", padx=(S(10), S(5)))
        label(box, word, "small", fg=MUTED).pack(side="left")
    return box


class CriteriaDialog(tk.Toplevel):
    """Popup explaining what every fundamental metric means and how it's colour-coded."""
    instance = None

    @classmethod
    def open(cls, app):
        if cls.instance is not None and cls.instance.winfo_exists():
            cls.instance.lift()
            cls.instance.focus_set()
            return
        cls.instance = cls(app)

    def __init__(self, app):
        super().__init__(app, bg=BG)
        self.title("How fundamentals are judged — Insight by Milton")
        self.transient(app)
        w, h = min(S(780), int(app.winfo_width() * 0.9)), min(S(720), int(app.winfo_height() * 0.9))
        x = app.winfo_rootx() + (app.winfo_width() - w) // 2
        y = app.winfo_rooty() + (app.winfo_height() - h) // 2
        self.geometry(f"{w}x{h}+{x}+{y}")
        self.minsize(S(560), S(400))

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=S(36), pady=(S(28), S(14)))
        label(head, "How each value is judged", "page_title").pack(anchor="w")
        wrap_label(head, "Every value is compared with a fixed rule of thumb that's widely used by investors. "
                         "What counts as normal differs a lot between industries — a software company and a "
                         "bank look very different — so treat the colours as a starting point for research, "
                         "not a verdict. Educational information only, not financial advice.",
                   "body", fg=MUTED).pack(fill="x", pady=(S(6), S(10)))
        rating_legend(head).pack(anchor="w")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", side="bottom")
        tk.Frame(foot, bg=BORDER, height=1).pack(fill="x")
        RoundButton(foot, "Close", self.destroy, kind="dark").pack(side="right", padx=S(36), pady=S(14))

        scroller = ScrollFrame(self)
        scroller.pack(fill="both", expand=True)
        body = tk.Frame(scroller.inner, bg=BG)
        body.pack(fill="both", expand=True, padx=S(36), pady=(S(4), S(24)))
        for group, metrics in FUNDAMENTALS:
            label(body, group.upper(), "eyebrow", fg=ACCENT).pack(anchor="w", pady=(S(22), S(4)))
            for spec in metrics:
                divider(body)
                row = tk.Frame(body, bg=BG)
                row.pack(fill="x", pady=S(12))
                rules = tk.Frame(row, bg=BG)
                rules.pack(side="right", anchor="n")
                text = tk.Frame(row, bg=BG)
                text.pack(side="left", fill="x", expand=True, anchor="n", padx=(0, S(24)))
                label(text, spec["name"], "card_title").pack(anchor="w")
                wrap_label(text, spec["about"], "small", fg=MUTED).pack(fill="x", pady=(S(2), 0))
                lines = describe_cutoffs(spec)
                if "zero" in spec:
                    lines.append((None, spec["zero"] + " — not counted"))
                for rating, rule in lines:
                    line = tk.Frame(rules, bg=BG)
                    line.pack(anchor="w", pady=S(1))
                    word = RATING_STYLE[rating][2] if rating else "Gray"
                    rating_pill(line, rating, word, width=6).pack(side="left")
                    label(line, rule, "small", width=24, anchor="w").pack(side="left", padx=(S(8), 0))
        divider(body, pady=(S(10), 0))
        wrap_label(body, "A gray “—” means Yahoo Finance doesn't report that value for the company. Gray values "
                         "aren't counted in the good / fair / weak tally.", "small",
                   fg=FAINT).pack(fill="x", pady=(S(12), 0))

        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_set()


# -----------------------------------------------------------------------------
# 8. Pages
# -----------------------------------------------------------------------------
class Page(tk.Frame):
    refresh_ms = None  # auto-refresh interval while the page is visible

    def __init__(self, app):
        super().__init__(app.body, bg=BG)
        self.app = app
        self.loaded = False
        self._timer = None
        self.build()

    def build(self):
        pass

    def first_load(self):
        pass

    def refresh(self):
        pass

    def show(self):
        if not self.loaded:
            self.loaded = True
            self.first_load()
        self._schedule()

    def hide(self):
        if self._timer:
            self.after_cancel(self._timer)
            self._timer = None

    def _schedule(self):
        if self.refresh_ms:
            self._timer = self.after(self.refresh_ms, self._tick)

    def _tick(self):
        self.refresh()
        self._schedule()

    def page_header(self, parent, title, subtitle):
        head = tk.Frame(parent, bg=BG)
        head.pack(fill="x", pady=(S(32), S(20)))
        text = tk.Frame(head, bg=BG)
        text.pack(side="left", anchor="w")
        label(text, title, "page_title").pack(anchor="w")
        label(text, subtitle, "body", fg=MUTED).pack(anchor="w", pady=(S(4), 0))
        return head


# ----------------------------------------------------------------- Home ------
class HomePage(Page):
    refresh_ms = 60_000

    def build(self):
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        body = self.scroller.inner
        wrap = tk.Frame(body, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(S(40), 0))
        self._build_hero(wrap)
        self._build_snapshot(wrap)
        self._build_insights(wrap)
        self._build_movers(wrap)
        self._build_quote(body)

    # --- hero ---------------------------------------------------------------
    def _build_hero(self, parent):
        hero = tk.Frame(parent, bg=BG)
        hero.pack(fill="x")
        hero.columnconfigure(0, weight=1)
        hero.columnconfigure(1, minsize=S(400))

        left = tk.Frame(hero, bg=BG)
        left.grid(row=0, column=0, sticky="nw")
        label(left, "INSIGHT\nBY MILTON", "hero", justify="left").pack(anchor="w")
        label(left, "Market data, economic signals and clear summaries for the curious reader. "
                    "A companion to The Milton Review.",
              "lead", justify="left", wraplength=S(470)).pack(anchor="w", pady=(S(14), S(24)))
        buttons = tk.Frame(left, bg=BG)
        buttons.pack(anchor="w")
        RoundButton(buttons, "Explore Markets", lambda: self.app.show("Markets")).pack(side="left")
        RoundButton(buttons, "Read The Milton Review", lambda: open_link(SITE_URL),
                    kind="ghost").pack(side="left", padx=S(12))

        brief = tk.Frame(hero, bg=SAND)
        brief.grid(row=0, column=1, sticky="nsew")
        inner = tk.Frame(brief, bg=SAND)
        inner.pack(fill="both", expand=True, padx=S(28), pady=S(26))
        label(inner, "TODAY'S BRIEF", "eyebrow", fg=ACCENT).pack(anchor="w")
        self.date_label = label(inner, "", "h2")
        self.date_label.pack(anchor="w", pady=(S(6), S(8)))
        status = tk.Frame(inner, bg=SAND)
        status.pack(anchor="w")
        self.status_dot = tk.Canvas(status, width=S(10), height=S(10), bg=SAND, highlightthickness=0)
        self.status_dot.pack(side="left", padx=(0, S(8)))
        self.status_label = label(status, "", "small", fg=MUTED)
        self.status_label.pack(side="left")
        divider(inner, pady=S(16))
        self.brief_label = wrap_label(inner, "Gathering today's numbers…", "body")
        self.brief_label.pack(fill="x")
        more = label(inner, "Open the full market view →", "body_semi", fg=ACCENT)
        more.pack(anchor="w", pady=(S(16), 0))
        make_clickable(more, lambda: self.app.show("Markets"))
        self.update_status()

    def update_status(self):
        now = now_eastern()
        is_open, text = market_status()
        self.date_label.configure(text=now.strftime("%A, %B %d").replace(" 0", " "))
        self.status_label.configure(text=text)
        self.status_dot.delete("all")
        self.status_dot.create_oval(1, 1, S(9), S(9), fill=UP if is_open else ACCENT, outline="")

    # --- snapshot -----------------------------------------------------------
    def _build_snapshot(self, parent):
        _, self.updated_label = section_header(parent, "Market Snapshot", "Loading…")
        grid = tk.Frame(parent, bg=BG)
        grid.pack(fill="x")
        self.snap = {}
        for i, (name, sym, kind) in enumerate(SNAPSHOT):
            row, col = divmod(i, 4)
            grid.columnconfigure(col, weight=1, uniform="snap")
            c = card(grid)
            c.grid(row=row, column=col, sticky="nsew",
                   padx=(0 if col == 0 else S(8), 0 if col == 3 else S(8)), pady=S(8))
            box = tk.Frame(c, bg=SURFACE)
            box.pack(fill="both", expand=True, padx=S(18), pady=S(16))
            top = tk.Frame(box, bg=SURFACE)
            top.pack(fill="x")
            label(top, name.upper(), "eyebrow", fg=MUTED).pack(side="left")
            label(top, sym, "small", fg=FAINT).pack(side="right")
            value = label(box, "—", "card_value")
            value.pack(anchor="w", pady=(S(6), 0))
            change = label(box, " ", "small_semi", fg=MUTED)
            change.pack(anchor="w")
            spark = Sparkline(box)
            spark.pack(fill="x", pady=(S(10), 0))
            make_clickable(c, lambda s=sym: self.app.open_symbol(s))
            hover_border(c)
            self.snap[sym] = (kind, value, change, spark)

    def _load_snapshot(self):
        self.app.worker.run(lambda: fetch_quotes([s for _, s, _ in SNAPSHOT]),
                            self._show_snapshot, self._snapshot_failed)

    def _show_snapshot(self, quotes):
        for sym, (kind, value, change, spark) in self.snap.items():
            q = quotes.get(sym)
            if not q:
                continue
            color = trend_color(q["change"])
            if kind == "yield":
                value.configure(text=f"{q['last']:.2f}%")
                change.configure(text=f"{q['change'] * 100:+.1f} bp", fg=color)
            else:
                value.configure(text=("$" if kind == "usd" else "") + fmt_price(q["last"]))
                change.configure(text=f"{fmt_change(q['change'])}  ({fmt_pct(q['pct'])})", fg=color)
            spark.set(q["spark"], color)
        self.updated_label.configure(text=f"Updated {clock_time(datetime.now())}", fg=FAINT)
        self.brief_label.configure(text=self._compose_brief(quotes))

    def _snapshot_failed(self, error):
        self.updated_label.configure(text="Couldn't reach Yahoo Finance — retrying in a minute", fg=DOWN)

    @staticmethod
    def _compose_brief(q):
        def verb(pct, up="rose", down="fell"):
            if abs(pct) < 0.05:
                return "was little changed"
            return f"{up if pct > 0 else down} {abs(pct):.2f}%"

        is_open, _ = market_status()
        when = "so far today" if is_open else "in the latest session"
        parts = []
        sp, nd = q.get("^GSPC"), q.get("^IXIC")
        if sp:
            line = f"The S&P 500 {verb(sp['pct'])} {when}"
            if nd:
                joiner = "and" if (sp["pct"] >= 0) == (nd["pct"] >= 0) else "while"
                line += f", {joiner} the Nasdaq {verb(nd['pct'], 'gained', 'slipped')}"
            parts.append(line + ".")
        tnx = q.get("^TNX")
        if tnx:
            direction = "up" if tnx["change"] > 0 else "down"
            parts.append(f"The 10-year Treasury yield sits at {tnx['last']:.2f}%, "
                         f"{direction} {abs(tnx['change'] * 100):.0f} bp.")
        btc = q.get("BTC-USD")
        if btc:
            parts.append(f"Bitcoin trades near ${btc['last']:,.0f} ({fmt_pct(btc['pct'])}).")
        return " ".join(parts) or "Market data is unavailable right now."

    # --- featured insights ---------------------------------------------------
    def _build_insights(self, parent):
        section_header(parent, "Featured Insights", "View all posts →", lambda: open_link(BLOG_URL))
        self.insights = tk.Frame(parent, bg=BG)
        self.insights.pack(fill="x")
        label(self.insights, "Loading the latest from The Milton Review…", "body", fg=FAINT).pack(anchor="w")

    def _show_insights(self, articles):
        for w in self.insights.winfo_children():
            w.destroy()
        if not articles:
            label(self.insights, "No articles yet.", "body", fg=FAINT).pack(anchor="w")
            return
        thumbs = []
        for i, art in enumerate(articles[:3]):
            self.insights.columnconfigure(i, weight=1, uniform="insight")
            c = card(self.insights)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else S(10), 0 if i == 2 else S(10)))
            thumb = Thumbnail(c, 190)
            thumb.pack(fill="x")
            thumbs.append(thumb)
            box = tk.Frame(c, bg=SURFACE)
            box.pack(fill="both", expand=True, padx=S(20), pady=S(18))
            meta = tk.Frame(box, bg=SURFACE)
            meta.pack(fill="x")
            avatar = tk.Canvas(meta, width=S(26), height=S(26), bg=SURFACE, highlightthickness=0)
            avatar.create_oval(1, 1, S(25), S(25), fill=ACCENT, outline="")
            avatar.create_text(S(13), S(13), text=(art["author"] or "M")[0].upper(), fill=BG,
                               font=FONTS["small_semi"])
            avatar.pack(side="left", padx=(0, S(8)))
            who = tk.Frame(meta, bg=SURFACE)
            who.pack(side="left")
            label(who, art["author"], "small").pack(anchor="w")
            label(who, short_date(art["date"]), "small", fg=FAINT).pack(anchor="w")
            wrap_label(box, art["title"], "card_title").pack(fill="x", pady=(S(14), S(6)))
            summary = art["summary"][:150].rsplit(" ", 1)[0] + "…" if len(art["summary"]) > 150 else art["summary"]
            wrap_label(box, summary, "small", fg=MUTED).pack(fill="x")
            label(box, "Read article →", "body_semi", fg=ACCENT).pack(anchor="w", pady=(S(12), 0))
            make_clickable(c, lambda url=art["link"]: open_link(url))
            hover_border(c)
        self.app.worker.run(lambda: fetch_images([a["image"] for a in articles[:3]]),
                            lambda imgs: [t.set_image(im) for t, im in zip(thumbs, imgs) if im])

    def _insights_failed(self, error):
        for w in self.insights.winfo_children():
            w.destroy()
        label(self.insights, "Couldn't load articles from themiltonreview.net.", "body", fg=DOWN).pack(anchor="w")

    # --- movers + newsletter -------------------------------------------------
    def _build_movers(self, parent):
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(S(44), 0))
        row.columnconfigure(0, weight=3, uniform="movers")
        row.columnconfigure(1, weight=2, uniform="movers")

        movers = card(row)
        movers.grid(row=0, column=0, sticky="nsew", padx=(0, S(10)))
        box = tk.Frame(movers, bg=SURFACE)
        box.pack(fill="both", expand=True, padx=S(24), pady=S(20))
        head = tk.Frame(box, bg=SURFACE)
        head.pack(fill="x", pady=(0, S(12)))
        label(head, "Today's Movers", "h2").pack(side="left")
        self.mover_kind = "day_gainers"
        ChipGroup(head, ["Gainers", "Losers", "Most Active"], self._switch_movers,
                  value="Gainers").pack(side="right")
        self.movers_list = tk.Frame(box, bg=SURFACE)
        self.movers_list.pack(fill="x")
        label(self.movers_list, "Loading…", "body", fg=FAINT).pack(anchor="w")

        brief = tk.Frame(row, bg=SAND)
        brief.grid(row=0, column=1, sticky="nsew", padx=(S(10), 0))
        inner = tk.Frame(brief, bg=SAND)
        inner.pack(fill="both", expand=True, padx=S(28), pady=S(28))
        label(inner, "THE MILTON\nBRIEF", "display", justify="left").pack(anchor="w")
        wrap_label(inner, "Join the newsletter and receive updates and top stories straight "
                          "to your inbox.", "body").pack(fill="x", pady=(S(14), S(20)))
        RoundButton(inner, "Subscribe on the website", lambda: open_link(SITE_URL)).pack(anchor="w")
        wrap_label(inner, "Educational commentary only — nothing in this app is financial advice.",
                   "small", fg=FAINT).pack(fill="x", side="bottom")

    def _switch_movers(self, choice):
        self.mover_kind = {"Gainers": "day_gainers", "Losers": "day_losers",
                           "Most Active": "most_actives"}[choice]
        self._load_movers()

    def _load_movers(self):
        kind = self.mover_kind
        self.app.worker.run(lambda: fetch_movers(kind),
                            lambda rows: self._show_movers(kind, rows), self._movers_failed)

    def _show_movers(self, kind, rows):
        if kind != self.mover_kind:
            return
        for w in self.movers_list.winfo_children():
            w.destroy()
        for i, m in enumerate(rows[:7]):
            if i:
                divider(self.movers_list)
            r = tk.Frame(self.movers_list, bg=SURFACE)
            r.pack(fill="x")
            r.columnconfigure(0, minsize=S(86))
            r.columnconfigure(1, weight=1)
            r.columnconfigure(2, minsize=S(90))
            label(r, m["symbol"], "body_semi", anchor="w").grid(row=0, column=0, sticky="w", pady=S(7), padx=(S(6), 0))
            name = m["name"] if len(m["name"]) <= 34 else m["name"][:33] + "…"
            label(r, name, "body", fg=MUTED, anchor="w").grid(row=0, column=1, sticky="w")
            label(r, fmt_price(m["price"]), "body", anchor="e").grid(row=0, column=2, sticky="e")
            change_pill(r, m["pct"], width=8).grid(row=0, column=3, sticky="e", padx=(S(14), S(6)))
            make_clickable(r, lambda s=m["symbol"]: self.app.open_symbol(s))
            add_hover(r, lambda r=r: set_bg(r, SAND), lambda r=r: set_bg(r, SURFACE))

    def _movers_failed(self, error):
        for w in self.movers_list.winfo_children():
            w.destroy()
        label(self.movers_list, "Movers are unavailable right now.", "body", fg=DOWN).pack(anchor="w")

    # --- rotating quote -------------------------------------------------------
    def _build_quote(self, parent):
        band = tk.Frame(parent, bg=BG)
        band.pack(fill="x", pady=(S(56), S(40)))
        self.quote_label = label(band, "", "quote", justify="center", wraplength=S(980))
        self.quote_label.pack(padx=S(56))
        self.quotes = QUOTES[:]
        random.shuffle(self.quotes)
        self._rotate_quote()

    def _rotate_quote(self):
        text, author = self.quotes[0]
        self.quotes.append(self.quotes.pop(0))
        self.quote_label.configure(text=f"“{text}”\n— {author}".upper())
        self.after(12_000, self._rotate_quote)

    # --- lifecycle ------------------------------------------------------------
    def first_load(self):
        self._load_snapshot()
        self._load_movers()
        self.app.get_articles(self._show_insights, self._insights_failed)

    def refresh(self):
        self._load_snapshot()


# -------------------------------------------------------------- Markets ------
class MarketsPage(Page):

    def build(self):
        self.symbol, self.range_key = "AAPL", "1Y"
        self.overlays = {"50-day MA", "Volume"}
        self.data = None
        self.prev_close = self.last_price = None
        self.request_id = 0
        self.hover_artists = None

        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        wrap = tk.Frame(self.scroller.inner, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(0, S(40)))

        # search row
        head = self.page_header(wrap, "Markets", "Search any stock, ETF, index, future or crypto — "
                                                 "by ticker or company name.")
        search = tk.Frame(head, bg=BG)
        search.pack(side="right", anchor="s")
        self.search = SearchEntry(search, "Search e.g. AAPL or Tesla", self.do_search, width=28)
        self.search.pack(side="left")
        RoundButton(search, "Search", self.do_search).pack(side="left", padx=(S(10), 0))

        popular = tk.Frame(wrap, bg=BG)
        popular.pack(fill="x", pady=(0, S(22)))
        label(popular, "POPULAR", "eyebrow", fg=FAINT).pack(side="left", padx=(0, S(12)))
        for sym in ("AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SPY", "QQQ", "BTC-USD"):
            RoundButton(popular, sym, lambda s=sym: self.load(s), kind="chip", font="chip",
                        padx=12, pady=5, radius=12).pack(side="left", padx=(0, S(6)))

        cols = tk.Frame(wrap, bg=BG)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, minsize=S(330))
        main = tk.Frame(cols, bg=BG)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, S(28)))
        side = tk.Frame(cols, bg=BG)
        side.grid(row=0, column=1, sticky="nsew")

        # quote header
        title = tk.Frame(main, bg=BG)
        title.pack(fill="x")
        self.name_label = label(title, "Loading…", "h2")
        self.name_label.pack(anchor="w")
        self.exchange_label = label(title, "", "small", fg=FAINT)
        self.exchange_label.pack(anchor="w")
        price_row = tk.Frame(main, bg=BG)
        price_row.pack(fill="x", pady=(S(8), 0))
        self.price_label = label(price_row, "", "price")
        self.price_label.pack(side="left", anchor="s")
        self.change_label = label(price_row, "", "lead")
        self.change_label.pack(side="left", anchor="s", padx=S(14), pady=(0, S(8)))
        self.asof_label = label(main, "", "small", fg=FAINT)
        self.asof_label.pack(anchor="w")

        controls = tk.Frame(main, bg=BG)
        controls.pack(fill="x", pady=(S(18), S(6)))
        self.range_chips = ChipGroup(controls, list(RANGES), self.set_range, value=self.range_key)
        self.range_chips.pack(side="left")
        RoundButton(controls, "Save chart", self.save_chart, kind="ghost", font="chip",
                    padx=12, pady=5, radius=12).pack(side="right")
        ChipGroup(controls, ["50-day MA", "200-day MA", "Volume"], self.set_overlays,
                  value=self.overlays, multi=True).pack(side="right", padx=S(12))
        self.period_label = label(main, "", "small_semi", fg=MUTED)
        self.period_label.pack(anchor="w", pady=(S(4), 0))

        self.fig = Figure(figsize=(9, 4.4), dpi=96 * SCALE, facecolor=BG)
        self.canvas = FigureCanvasTkAgg(self.fig, master=main)
        chart = self.canvas.get_tk_widget()
        chart.configure(height=S(440), bg=BG, highlightthickness=0)
        chart.pack(fill="x", pady=(S(4), 0))
        self.canvas.mpl_connect("motion_notify_event", self._on_hover)
        self.canvas.mpl_connect("figure_leave_event", lambda e: self._hide_hover())

        self.fund_section = tk.Frame(main, bg=BG)   # only packed for companies, see _fill_fundamentals
        self.headlines_title = label(main, "Headlines", "h2")
        self.headlines_title.pack(anchor="w", pady=(S(28), S(10)))
        self.news_box = tk.Frame(main, bg=BG)
        self.news_box.pack(fill="x")

        # sidebar
        self.watch_button = RoundButton(side, "+ Add to Watchlist", self.toggle_watch)
        self.watch_button.pack(anchor="w", pady=(S(4), S(18)))
        stats = card(side)
        stats.pack(fill="x")
        stats_box = tk.Frame(stats, bg=SURFACE)
        stats_box.pack(fill="both", expand=True, padx=S(22), pady=S(18))
        label(stats_box, "Key Statistics", "h2").pack(anchor="w", pady=(0, S(8)))
        self.stats_box = tk.Frame(stats_box, bg=SURFACE)
        self.stats_box.pack(fill="x")
        self.about_title = label(side, "", "h2")
        self.about_title.pack(anchor="w", pady=(S(24), S(6)))
        self.about_label = wrap_label(side, "", "small", fg=MUTED)
        self.about_label.pack(fill="x")

        self.app.watchlist.listeners.append(self._update_watch_button)

    def first_load(self):
        self.load(self.symbol)

    def show(self):
        super().show()
        self._update_watch_button()

    # --- actions --------------------------------------------------------------
    def do_search(self):
        query = self.search.get()
        if query:
            self.search.clear()
            self.load(query)

    def load(self, query):
        self.loaded = True
        self.request_id += 1
        rid, rk = self.request_id, self.range_key
        self.scroller.to_top()
        self._chart_message(f"Loading {query.upper()}…")
        self.app.set_status(f"Loading {query.upper()}…")
        self.app.worker.run(lambda: load_symbol(query, rk),
                            lambda d: self._show(rid, d), lambda e: self._failed(rid, e))

    def set_range(self, range_key):
        self.range_key = range_key
        if not self.data:
            return
        self.request_id += 1
        rid, sym = self.request_id, self.data["symbol"]
        self._chart_message("Loading…")
        self.app.worker.run(lambda: fetch_history(sym, range_key),
                            lambda h: self._show_range(rid, h), lambda e: self._failed(rid, e))

    def set_overlays(self, selected):
        self.overlays = set(selected)
        if self.data:
            self._draw_chart()

    def toggle_watch(self):
        if not self.data:
            return
        sym = self.data["symbol"]
        if sym in self.app.watchlist:
            self.app.watchlist.remove(sym)
        else:
            info = self.data["info"]
            self.app.watchlist.add(sym, info.get("shortName") or info.get("longName") or "")

    def _update_watch_button(self):
        on = bool(self.data) and self.data["symbol"] in self.app.watchlist
        self.watch_button.update_button("✓ In your Watchlist" if on else "+ Add to Watchlist",
                                        "ghost" if on else "primary")

    def save_chart(self):
        if not self.data:
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png", filetypes=[("PNG image", "*.png"), ("PDF", "*.pdf")],
            initialfile=f"{self.data['symbol']}_{self.range_key}.png")
        if path:
            self._hide_hover()
            self.fig.savefig(path, dpi=200, facecolor=BG)
            self.app.set_status(f"Chart saved to {path}")

    # --- results ----------------------------------------------------------------
    def _show(self, rid, data):
        if rid != self.request_id:
            return
        self.data = data
        info, sym = data["info"], data["symbol"]
        name = info.get("longName") or info.get("shortName") or sym
        self.name_label.configure(text=f"{name}  ({sym})")
        exchange = info.get("fullExchangeName") or info.get("exchange") or ""
        currency = info.get("currency") or ""
        self.exchange_label.configure(text=" · ".join(x for x in (exchange, currency) if x))

        price = info.get("regularMarketPrice") or info.get("currentPrice") or float(data["hist"]["Close"].iloc[-1])
        prev = info.get("regularMarketPreviousClose") or info.get("previousClose")
        self.prev_close, self.last_price = prev, price
        self.price_label.configure(text=fmt_price(price))
        if prev:
            change = price - prev
            pct = change / prev * 100
            self.change_label.configure(text=f"{fmt_change(change)} ({fmt_pct(pct)}) today",
                                        fg=trend_color(change))
        else:
            self.change_label.configure(text="")
        is_open, _ = market_status()
        self.asof_label.configure(text=f"{'Live' if is_open else 'At close'} · as of "
                                       f"{clock_time(datetime.now())}. Prices may be delayed.")

        self._fill_stats(info)
        about = info.get("longBusinessSummary") or ""
        self.about_title.configure(text=f"About {info.get('shortName') or sym}" if about else "")
        self.about_label.configure(text=(about[:520].rsplit(" ", 1)[0] + "…") if len(about) > 520 else about)
        self._fill_fundamentals(info)
        self._fill_news(data["news"])
        self._update_watch_button()
        self._draw_chart()
        self.app.set_status(f"Showing {sym}")

    def _show_range(self, rid, hist):
        if rid != self.request_id:
            return
        if hist.empty:
            self._chart_message("No data for this range.")
            return
        self.data["hist"] = hist
        self._draw_chart()

    def _failed(self, rid, error):
        if rid != self.request_id:
            return
        msg = str(error) if isinstance(error, LookupError) else "Couldn't load market data. Check your connection."
        self._chart_message(msg)
        self.app.set_status(msg)

    def _fill_stats(self, info):
        for w in self.stats_box.winfo_children():
            w.destroy()

        def rng(lo, hi):
            return f"{fmt_price(lo)} – {fmt_price(hi)}" if not (is_missing(lo) or is_missing(hi)) else None

        div = info.get("trailingAnnualDividendYield")
        rows = [
            ("Open", fmt_price(info.get("regularMarketOpen") or info.get("open"))),
            ("Previous close", fmt_price(info.get("regularMarketPreviousClose"))),
            ("Day range", rng(info.get("regularMarketDayLow") or info.get("dayLow"),
                              info.get("regularMarketDayHigh") or info.get("dayHigh"))),
            ("52-week range", rng(info.get("fiftyTwoWeekLow"), info.get("fiftyTwoWeekHigh"))),
            ("Volume", fmt_big(info.get("regularMarketVolume") or info.get("volume"))),
            ("Avg. volume", fmt_big(info.get("averageVolume"))),
            ("Market cap", fmt_big(info.get("marketCap"))),
            ("P/E (TTM)", fmt_price(info.get("trailingPE"))),
            ("Forward P/E", fmt_price(info.get("forwardPE"))),
            ("EPS (TTM)", fmt_price(info.get("trailingEps"))),
            ("Dividend yield", f"{div * 100:.2f}%" if div else None),
            ("Beta", fmt_price(info.get("beta"))),
            ("Sector", info.get("sector")),
            ("Industry", info.get("industry")),
        ]
        rows = [(k, v) for k, v in rows if v and v != "—"]
        if not rows:
            label(self.stats_box, "No statistics available.", "small", fg=FAINT).pack(anchor="w")
        for i, (k, v) in enumerate(rows):
            if i:
                divider(self.stats_box)
            r = tk.Frame(self.stats_box, bg=SURFACE)
            r.pack(fill="x", pady=S(6))
            label(r, k, "small", fg=MUTED).pack(side="left")
            label(r, v, "small_semi").pack(side="right")

    def _fill_fundamentals(self, info):
        """Colour-coded fundamental analysis cards. Hidden for ETFs, indices, crypto and futures."""
        section = self.fund_section
        for w in section.winfo_children():
            w.destroy()
        results = [(group, [(spec, *judge_metric(spec, info)) for spec in metrics])
                   for group, metrics in FUNDAMENTALS]
        rated = [r for _, rows in results for _, r, _ in rows if r]
        if info.get("quoteType") != "EQUITY" or len(rated) < 3:
            section.pack_forget()
            return
        section.pack(fill="x", pady=(S(32), 0), before=self.headlines_title)

        head = tk.Frame(section, bg=BG)
        head.pack(fill="x")
        title = tk.Frame(head, bg=BG)
        title.pack(side="left", anchor="s")
        label(title, "Fundamental Analysis", "h2").pack(anchor="w")
        sector = " · ".join(x for x in (info.get("sector"), info.get("industry")) if x)
        label(title, (sector + "  ·  " if sector else "") + "Judged against general rules of thumb",
              "small", fg=MUTED).pack(anchor="w")
        rating_legend(head).pack(side="right", anchor="s", pady=(0, S(2)))
        tally = tk.Frame(head, bg=BG)
        tally.pack(side="right", anchor="s", padx=(0, S(14)))
        for rating in ("good", "fair", "weak"):
            word = RATING_STYLE[rating][2].lower()
            rating_pill(tally, rating, f"{rated.count(rating)} {word}", width=0).pack(side="left", padx=(S(6), 0))

        grid = tk.Frame(section, bg=BG)
        grid.pack(fill="x", pady=(S(14), 0))
        for col, (group, rows) in enumerate(results):
            grid.columnconfigure(col, weight=1, uniform="fund")
            c = card(grid)
            c.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else S(6), 0 if col == 3 else S(6)))
            box = tk.Frame(c, bg=SURFACE)
            box.pack(fill="both", expand=True, padx=S(16), pady=S(14))
            label(box, group.upper(), "eyebrow", fg=ACCENT).pack(anchor="w", pady=(0, S(6)))
            for spec, rating, text in rows:
                row = tk.Frame(box, bg=SURFACE)
                row.pack(fill="x", pady=S(3))
                label(row, spec["name"], "small", fg=MUTED).pack(side="left")
                rating_pill(row, rating, text, width=8).pack(side="right")
                rules = "   ".join(f"{RATING_STYLE[r][2]}: {t}" for r, t in describe_cutoffs(spec))
                Tooltip(row, f"{spec['name']}\n{spec['about']}\n\n{rules}")

        foot = tk.Frame(section, bg=BG)
        foot.pack(fill="x", pady=(S(10), 0))
        link = label(foot, "How is each value judged? →", "body_semi", fg=ACCENT)
        link.pack(side="left")
        make_clickable(link, lambda: CriteriaDialog.open(self.app))
        label(foot, "Hover any value for details. Educational only — not financial advice.",
              "small", fg=FAINT).pack(side="right")

    def _fill_news(self, news):
        for w in self.news_box.winfo_children():
            w.destroy()
        if not news:
            label(self.news_box, "No recent headlines.", "body", fg=FAINT).pack(anchor="w")
            return
        rows = [NewsRow(self.news_box, n["title"], f"{n['publisher']} · {time_ago(n['date'])}",
                        link=n["link"], thumb=(96, 64)) for n in news]
        for r in rows:
            r.pack(fill="x")
        self.app.worker.run(lambda: fetch_images([n["image"] for n in news]),
                            lambda imgs: [r.set_image(im) for r, im in zip(rows, imgs) if im])

    # --- chart ------------------------------------------------------------------
    def _chart_message(self, text):
        self.fig.clear()
        self.hover_artists = None
        self.fig.text(0.5, 0.5, text, ha="center", va="center", color=FAINT, fontsize=11)
        self.canvas.draw_idle()

    def _draw_chart(self):
        hist = self.data["hist"]
        self.fig.clear()
        intraday = self.range_key in ("1D", "5D")
        show_volume = "Volume" in self.overlays and hist["Volume"].fillna(0).sum() > 0
        if show_volume:
            gs = self.fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.06)
            ax = self.fig.add_subplot(gs[0])
            axv = self.fig.add_subplot(gs[1], sharex=ax)
        else:
            ax, axv = self.fig.add_subplot(111), None
        style_axes(ax, price_on_right=True)

        # plot against the bar number (not the date) so nights and weekends don't leave gaps
        x = np.arange(len(hist))
        close = hist["Close"].to_numpy()
        base = self.prev_close if (self.range_key == "1D" and self.prev_close) else close[0]
        last = self.last_price if self.range_key == "1D" else close[-1]
        period_change = (last / base - 1) * 100 if base else 0
        color = trend_color(period_change)
        if color == MUTED:
            color = INK

        series = [close]
        if not intraday:
            for name, col, c, style in (("50-day MA", "MA50", ACCENT, "-"), ("200-day MA", "MA200", FAINT, "--")):
                if name in self.overlays and hist[col].notna().any():
                    ax.plot(x, hist[col], color=c, linewidth=1.2, linestyle=style, label=name)
                    series.append(hist[col].dropna().to_numpy())
        lo = min(s.min() for s in series)
        hi = max(s.max() for s in series)
        if self.range_key == "1D" and self.prev_close:
            lo, hi = min(lo, self.prev_close), max(hi, self.prev_close)
            ax.axhline(self.prev_close, color=FAINT, linewidth=0.9, linestyle=(0, (2, 3)))
            ax.text(0.005, self.prev_close, " prev close", color=FAINT, fontsize=7.5, va="bottom",
                    transform=ax.get_yaxis_transform())
        pad = (hi - lo) * 0.08 or hi * 0.01
        ax.set_ylim(lo - pad, hi + pad)
        ax.fill_between(x, close, lo - pad, color=color, alpha=0.07, linewidth=0)
        ax.plot(x, close, color=color, linewidth=1.7, label="Price")
        ax.set_xlim(0, max(len(x) - 1, 1))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:,.2f}" if hi < 1000 else f"{v:,.0f}"))
        handles, names = ax.get_legend_handles_labels()
        if len(handles) > 1:
            order = [names.index("Price")] + [i for i, n in enumerate(names) if n != "Price"]
            ax.legend([handles[i] for i in order], [names[i] for i in order], loc="upper left",
                      frameon=False, fontsize=8, ncol=3, labelcolor=MUTED)

        # date labels
        fmt = {"1D": "%I:%M %p", "5D": "%a %d", "1M": "%b %d", "6M": "%b %d", "YTD": "%b %d",
               "1Y": "%b '%y", "5Y": "%Y", "MAX": "%Y"}[self.range_key]
        ticks = sorted(set(np.linspace(0, len(x) - 1, 7).round().astype(int)))
        labels = [hist.index[i].strftime(fmt).lstrip("0") for i in ticks]
        bottom = axv or ax
        bottom.set_xticks(ticks)
        bottom.set_xticklabels(labels)
        tick_labels = bottom.get_xticklabels()
        if len(tick_labels) > 1:
            tick_labels[0].set_horizontalalignment("left")
            tick_labels[-1].set_horizontalalignment("right")
        if axv is not None:
            style_axes(axv, price_on_right=True)
            ax.tick_params(labelbottom=False)
            axv.bar(x, hist["Volume"], color=BORDER, width=0.8)
            axv.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: fmt_big(v) if v else ""))
            axv.yaxis.set_major_locator(MaxNLocator(2))
            axv.grid(False)

        word = RANGE_WORDS[self.range_key]
        self.period_label.configure(text=f"{fmt_pct(period_change)} {word}", fg=trend_color(period_change))

        # hover crosshair + readout
        vline = ax.axvline(0, color=MUTED, linewidth=0.8, linestyle=":", visible=False)
        dot, = ax.plot([], [], "o", color=color, markersize=5, markeredgecolor=BG, markeredgewidth=1.5)
        tip = ax.text(0.99, 0.98, "", transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
                      color=INK, bbox=dict(boxstyle="round,pad=0.5", fc=SURFACE, ec=BORDER), visible=False)
        self.hover_artists = (ax, axv, vline, dot, tip, close, base, intraday)
        self.fig.subplots_adjust(left=0.02, right=0.92, top=0.97, bottom=0.08)
        self.canvas.draw_idle()

    def _on_hover(self, event):
        if not self.hover_artists or not self.data:
            return
        ax, axv, vline, dot, tip, close, base, intraday = self.hover_artists
        if event.inaxes not in (ax, axv) or event.xdata is None:
            self._hide_hover()
            return
        i = int(min(max(round(event.xdata), 0), len(close) - 1))
        when = self.data["hist"].index[i]
        stamp = when.strftime("%a %b %d, %I:%M %p" if intraday else "%a %b %d, %Y").replace(" 0", " ")
        vol = self.data["hist"]["Volume"].iloc[i]
        tip.set_text(f"{stamp}\n{fmt_price(close[i])}   {fmt_pct((close[i] / base - 1) * 100)}"
                     + (f"\nVol {fmt_big(vol)}" if vol else ""))
        vline.set_xdata([i, i])
        dot.set_data([i], [close[i]])
        for a in (vline, dot, tip):
            a.set_visible(True)
        self.canvas.draw_idle()

    def _hide_hover(self):
        if self.hover_artists:
            for a in self.hover_artists[2:5]:
                a.set_visible(False)
            self.canvas.draw_idle()


class NewsRow(tk.Frame):
    """Thumbnail + headline row used on the News and Markets pages."""

    def __init__(self, parent, title, meta, link=None, excerpt=None, thumb=(120, 80), bg=BG):
        super().__init__(parent, bg=bg)
        self.base_bg = bg
        inner = tk.Frame(self, bg=bg)
        inner.pack(fill="x", padx=S(8), pady=S(12))
        self.thumb = Thumbnail(inner, thumb[1], width=thumb[0], placeholder=meta)
        self.thumb.pack(side="left", anchor="n", padx=(0, S(16)))
        text = tk.Frame(inner, bg=bg)
        text.pack(side="left", fill="x", expand=True, anchor="n")
        label(text, meta, "small", fg=FAINT, anchor="w").pack(fill="x")
        wrap_label(text, title, "card_title").pack(fill="x", pady=(S(2), 0))
        if excerpt:
            wrap_label(text, excerpt, "small", fg=MUTED).pack(fill="x", pady=(S(4), 0))
        divider(self)
        if link:
            make_clickable(self, lambda: open_link(link))
            add_hover(self, lambda: set_bg(self, SAND), lambda: set_bg(self, self.base_bg))

    def set_image(self, image):
        self.thumb.set_image(image)


# ----------------------------------------------------------------- News ------
class NewsPage(Page):
    refresh_ms = 5 * 60_000
    TOPICS = {"Top Stories": "stock market", "Economy": "economy", "The Fed": "federal reserve",
              "Earnings": "earnings", "Tech": "tech stocks", "Energy": "oil prices", "Crypto": "bitcoin"}

    def build(self):
        self.query = "stock market"
        self.request_id = 0
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        wrap = tk.Frame(self.scroller.inner, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(0, S(40)))

        head = self.page_header(wrap, "News", "Market headlines from around the web, plus the "
                                              "latest analysis from The Milton Review.")
        search = tk.Frame(head, bg=BG)
        search.pack(side="right", anchor="s")
        self.search = SearchEntry(search, "Search news e.g. inflation", self.do_search, width=26)
        self.search.pack(side="left")
        RoundButton(search, "Search", self.do_search).pack(side="left", padx=(S(10), 0))

        self.topics = ChipGroup(wrap, list(self.TOPICS), self.set_topic, value="Top Stories")
        self.topics.pack(anchor="w", pady=(0, S(20)))

        cols = tk.Frame(wrap, bg=BG)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=3, uniform="news")
        cols.columnconfigure(1, weight=2, uniform="news")

        left = tk.Frame(cols, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, S(24)))
        self.headline_title = label(left, "Market Headlines", "h2")
        self.headline_title.pack(anchor="w")
        divider(left, pady=(S(10), 0))
        self.headlines = tk.Frame(left, bg=BG)
        self.headlines.pack(fill="x")

        right = card(cols, bg=SAND, border=False)
        right.grid(row=0, column=1, sticky="nsew", padx=(S(8), 0))
        rbox = tk.Frame(right, bg=SAND)
        rbox.pack(fill="both", expand=True, padx=S(24), pady=S(22))
        top = tk.Frame(rbox, bg=SAND)
        top.pack(fill="x")
        label(top, "From The Milton Review", "h2").pack(side="left")
        more = label(top, "Visit blog →", "small_semi", fg=ACCENT)
        more.pack(side="right")
        make_clickable(more, lambda: open_link(BLOG_URL))
        divider(rbox, pady=(S(10), 0))
        self.articles = tk.Frame(rbox, bg=SAND)
        self.articles.pack(fill="x")
        label(self.articles, "Loading…", "body", fg=FAINT).pack(anchor="w", pady=S(12))

    def first_load(self):
        self._load_headlines()
        self.app.get_articles(self._show_articles, self._articles_failed)

    def refresh(self):
        self._load_headlines()

    def set_topic(self, topic):
        self.query = self.TOPICS[topic]
        self.headline_title.configure(text="Market Headlines" if topic == "Top Stories" else topic)
        self._load_headlines()

    def do_search(self):
        query = self.search.get()
        if query:
            self.query = query
            self.topics.set(None)
            self.headline_title.configure(text=f"Results for “{query}”")
            self._load_headlines()

    def _load_headlines(self):
        self.request_id += 1
        rid, query = self.request_id, self.query
        for w in self.headlines.winfo_children():
            w.destroy()
        label(self.headlines, "Loading headlines…", "body", fg=FAINT).pack(anchor="w", pady=S(12))
        self.app.worker.run(lambda: fetch_headlines(query, count=14),
                            lambda items: self._show_headlines(rid, items),
                            lambda e: self._headlines_failed(rid))

    def _show_headlines(self, rid, items):
        if rid != self.request_id:
            return
        for w in self.headlines.winfo_children():
            w.destroy()
        if not items:
            label(self.headlines, "No headlines found.", "body", fg=FAINT).pack(anchor="w", pady=S(12))
            return
        rows = [NewsRow(self.headlines, n["title"], f"{n['publisher'].upper()}  ·  {time_ago(n['date'])}",
                        link=n["link"]) for n in items]
        for r in rows:
            r.pack(fill="x")
        self.app.worker.run(lambda: fetch_images([n["image"] for n in items]),
                            lambda imgs: [r.set_image(im) for r, im in zip(rows, imgs) if im])

    def _headlines_failed(self, rid):
        if rid != self.request_id:
            return
        for w in self.headlines.winfo_children():
            w.destroy()
        label(self.headlines, "Couldn't load headlines. Check your connection.", "body",
              fg=DOWN).pack(anchor="w", pady=S(12))

    def _show_articles(self, articles):
        for w in self.articles.winfo_children():
            w.destroy()
        rows = []
        for a in articles[:8]:
            excerpt = a["summary"][:120].rsplit(" ", 1)[0] + "…" if len(a["summary"]) > 120 else a["summary"]
            r = NewsRow(self.articles, a["title"], f"{a['author']}  ·  {short_date(a['date'])}",
                        link=a["link"], excerpt=excerpt, thumb=(96, 72), bg=SAND)
            r.pack(fill="x")
            rows.append(r)
        self.app.worker.run(lambda: fetch_images([a["image"] for a in articles[:8]]),
                            lambda imgs: [r.set_image(im) for r, im in zip(rows, imgs) if im])

    def _articles_failed(self, error):
        for w in self.articles.winfo_children():
            w.destroy()
        label(self.articles, "Couldn't reach themiltonreview.net.", "body", fg=DOWN).pack(anchor="w", pady=S(12))


# ------------------------------------------------------------ Watchlist ------
class WatchlistPage(Page):
    refresh_ms = 60_000
    # header, min width, stretch, alignment
    COLUMNS = [("SYMBOL", 96, 0, "w"), ("NAME", 200, 1, "w"), ("LAST", 104, 0, "e"),
               ("CHANGE", 96, 0, "e"), ("% CHANGE", 104, 0, "e"), ("DAY RANGE", 180, 0, "e"),
               ("VOLUME", 100, 0, "e"), ("1 MONTH", 150, 0, "e"), ("", 44, 0, "e")]

    def build(self):
        self.quotes = {}
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        wrap = tk.Frame(self.scroller.inner, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(0, S(40)))

        head = self.page_header(wrap, "Watchlist", "Your saved symbols, refreshed every minute. "
                                                   "Click a row to open its chart.")
        controls = tk.Frame(head, bg=BG)
        controls.pack(side="right", anchor="s")
        self.entry = SearchEntry(controls, "Add a symbol e.g. COST", self.add_symbol, width=22)
        self.entry.pack(side="left")
        RoundButton(controls, "Add", self.add_symbol).pack(side="left", padx=(S(10), 0))
        RoundButton(controls, "Refresh", self.refresh, kind="ghost").pack(side="left", padx=(S(10), 0))

        self.message = label(wrap, "", "small", fg=FAINT)
        self.message.pack(anchor="w", pady=(0, S(8)))

        table = card(wrap)
        table.pack(fill="x")
        self.table = tk.Frame(table, bg=SURFACE)
        self.table.pack(fill="x", padx=S(8), pady=S(6))
        self.app.watchlist.listeners.append(self._watchlist_changed)

    def _configure_columns(self, frame):
        for i, (_, width, stretch, _) in enumerate(self.COLUMNS):
            frame.columnconfigure(i, minsize=S(width), weight=stretch)

    def first_load(self):
        self.render()
        self.refresh()

    def refresh(self):
        symbols = self.app.watchlist.symbols
        if not symbols:
            return
        self.message.configure(text="Refreshing…", fg=FAINT)
        self.app.worker.run(lambda: fetch_quotes(symbols), self._got_quotes, self._quotes_failed)

    def _got_quotes(self, quotes):
        self.quotes.update(quotes)
        self.message.configure(text=f"Updated {clock_time(datetime.now())}  ·  "
                                    f"{len(self.app.watchlist.symbols)} symbols", fg=FAINT)
        self.render()

    def _quotes_failed(self, error):
        self.message.configure(text="Couldn't refresh prices. Check your connection.", fg=DOWN)

    def _watchlist_changed(self):
        if self.loaded:
            self.render()
            missing = [s for s in self.app.watchlist.symbols if s not in self.quotes]
            if missing:
                self.app.worker.run(lambda: fetch_quotes(missing), self._got_quotes)

    def render(self):
        for w in self.table.winfo_children():
            w.destroy()
        header = tk.Frame(self.table, bg=SURFACE)
        header.pack(fill="x")
        self._configure_columns(header)
        for i, (title, _, _, anchor) in enumerate(self.COLUMNS):
            label(header, title, "eyebrow", fg=FAINT).grid(row=0, column=i, sticky=anchor,
                                                           padx=S(10), pady=(S(10), S(8)))
        items = self.app.watchlist.items
        if not items:
            divider(self.table)
            label(self.table, "Your watchlist is empty. Add a symbol above, or use “Add to Watchlist” "
                              "on the Markets page.", "body", fg=MUTED).pack(pady=S(36))
            return
        for item in items:
            divider(self.table)
            self._row(item)

    def _row(self, item):
        sym = item["symbol"]
        q = self.quotes.get(sym)
        row = tk.Frame(self.table, bg=SURFACE)
        row.pack(fill="x")
        self._configure_columns(row)
        color = trend_color(q["change"]) if q else MUTED
        cells = [
            (sym, "body_semi", INK),
            (item.get("name") or "", "body", MUTED),
            (fmt_price(q["last"]) if q else "…", "body_semi", INK),
            (fmt_change(q["change"]) if q else "", "body", color),
            None,  # % change pill
            (f"{fmt_price(q['low'])} – {fmt_price(q['high'])}" if q else "", "small", MUTED),
            (fmt_big(q["volume"]) if q else "", "small", MUTED),
        ]
        for i, cell in enumerate(cells):
            anchor = self.COLUMNS[i][3]
            if cell is None:
                widget = change_pill(row, q["pct"], width=8) if q else label(row, "")
            else:
                text, font, fg = cell
                widget = label(row, text, font, fg=fg)
            widget.grid(row=0, column=i, sticky=anchor, padx=S(10), pady=S(12))
        spark = Sparkline(row, height=28, width=130)
        spark.grid(row=0, column=7, sticky="e", padx=S(10))
        if q:
            spark.set(q["spark"], color)
        remove = label(row, "✕", "body", fg=FAINT)
        remove.grid(row=0, column=8, sticky="e", padx=S(10))
        make_clickable(row, lambda: self.app.open_symbol(sym))
        remove.unbind("<Button-1>")
        remove.bind("<Button-1>", lambda e: self.app.watchlist.remove(sym))
        remove.bind("<Enter>", lambda e: remove.configure(fg=DOWN), add="+")
        remove.bind("<Leave>", lambda e: remove.configure(fg=FAINT), add="+")
        add_hover(row, lambda: set_bg(row, SAND), lambda: set_bg(row, SURFACE))

    def add_symbol(self):
        query = self.entry.get()
        if not query:
            return
        self.entry.clear()
        self.message.configure(text=f"Looking up {query.upper()}…", fg=FAINT)

        def lookup():
            sym = query.upper()
            quotes = fetch_quotes([sym]) if TICKER_RE.match(sym) else {}
            name = ""
            if sym not in quotes:
                sym, name = search_symbol(query)
                quotes = fetch_quotes([sym])
            if sym not in quotes:
                raise LookupError(f"Couldn't find “{query}”.")
            if not name:
                try:
                    match = [x for x in yf.Search(sym, max_results=5, news_count=0).quotes
                             if x.get("symbol") == sym]
                    name = (match[0].get("shortname") or match[0].get("longname") or "") if match else ""
                except Exception:
                    pass
            return sym, name, quotes

        def done(result):
            sym, name, quotes = result
            self.quotes.update(quotes)
            if sym in self.app.watchlist:
                self.message.configure(text=f"{sym} is already on your watchlist.", fg=FAINT)
            else:
                self.app.watchlist.add(sym, name)
                self.message.configure(text=f"Added {sym}.", fg=UP)

        def failed(error):
            text = str(error) if isinstance(error, LookupError) else "Lookup failed. Check your connection."
            self.message.configure(text=text, fg=DOWN)

        self.app.worker.run(lookup, done, failed)


# ---------------------------------------------------------- Bond Market ------
class BondPage(Page):
    refresh_ms = 30 * 60_000

    def build(self):
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        wrap = tk.Frame(self.scroller.inner, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(0, S(40)))

        head = self.page_header(wrap, "Bond Market", "The U.S. Treasury par yield curve, straight from "
                                                     "treasury.gov and updated each business day.")
        RoundButton(head, "Refresh", self.refresh, kind="ghost").pack(side="right", anchor="s")
        self.asof = label(wrap, "Loading Treasury data…", "small", fg=FAINT)
        self.asof.pack(anchor="w", pady=(0, S(12)))

        # signal cards
        signals = tk.Frame(wrap, bg=BG)
        signals.pack(fill="x")
        self.signals = {}
        for i, key in enumerate(("10-Year Yield", "2-Year Yield", "2s10s Spread", "3M–10Y Spread")):
            signals.columnconfigure(i, weight=1, uniform="sig")
            c = card(signals)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else S(8), 0 if i == 3 else S(8)))
            box = tk.Frame(c, bg=SURFACE)
            box.pack(fill="both", expand=True, padx=S(20), pady=S(16))
            label(box, key.upper(), "eyebrow", fg=MUTED).pack(anchor="w")
            value = label(box, "—", "card_value")
            value.pack(anchor="w", pady=(S(6), S(2)))
            sub = tk.Frame(box, bg=SURFACE)
            sub.pack(anchor="w")
            self.signals[key] = (value, sub)

        # yield curve chart + table
        row = tk.Frame(wrap, bg=BG)
        row.pack(fill="x", pady=(S(36), 0))
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, minsize=S(330))
        left = tk.Frame(row, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, S(28)))
        label(left, "The Yield Curve", "h2").pack(anchor="w")
        label(left, "Today compared with one month and one year ago", "small", fg=MUTED).pack(anchor="w")
        self.curve_fig = Figure(figsize=(8, 3.8), dpi=96 * SCALE, facecolor=BG)
        self.curve_canvas = FigureCanvasTkAgg(self.curve_fig, master=left)
        w = self.curve_canvas.get_tk_widget()
        w.configure(height=S(380), bg=BG, highlightthickness=0)
        w.pack(fill="x", pady=(S(8), 0))

        table = card(row)
        table.grid(row=0, column=1, sticky="new")
        tbox = tk.Frame(table, bg=SURFACE)
        tbox.pack(fill="both", expand=True, padx=S(22), pady=S(18))
        label(tbox, "Yields by Maturity", "h2").pack(anchor="w", pady=(0, S(8)))
        self.table = tk.Frame(tbox, bg=SURFACE)
        self.table.pack(fill="x")

        # spread history
        label(wrap, "Recession Watch", "h2").pack(anchor="w", pady=(S(36), 0))
        label(wrap, "Spread between long and short Treasury yields over the past two years. "
                    "Below zero means the curve is inverted.", "small", fg=MUTED).pack(anchor="w")
        self.spread_fig = Figure(figsize=(10, 3), dpi=96 * SCALE, facecolor=BG)
        self.spread_canvas = FigureCanvasTkAgg(self.spread_fig, master=wrap)
        w = self.spread_canvas.get_tk_widget()
        w.configure(height=S(300), bg=BG, highlightthickness=0)
        w.pack(fill="x", pady=(S(8), 0))

        # explainer
        explain = tk.Frame(wrap, bg=SAND)
        explain.pack(fill="x", pady=(S(32), 0))
        ebox = tk.Frame(explain, bg=SAND)
        ebox.pack(fill="both", expand=True, padx=S(32), pady=S(28))
        label(ebox, "READING THE CURVE", "eyebrow", fg=ACCENT).pack(anchor="w")
        self.summary = wrap_label(ebox, "", "lead")
        self.summary.pack(fill="x", pady=(S(8), S(14)))
        wrap_label(ebox,
                   "The yield curve plots what the U.S. government pays to borrow for different lengths "
                   "of time. Normally, lenders demand more to tie money up for longer, so the curve slopes "
                   "upward. When short-term yields rise above long-term ones the curve “inverts” — a sign "
                   "that investors expect the Federal Reserve to cut rates because growth is slowing. "
                   "Inversions of the 2-year/10-year and 3-month/10-year spreads have preceded most U.S. "
                   "recessions since the 1970s, though the lag has ranged from months to years, and a "
                   "signal is not a guarantee.", "body", fg=MUTED).pack(fill="x")

    def first_load(self):
        self.refresh()

    def refresh(self):
        self._message(self.curve_fig, self.curve_canvas, "Loading…")
        self.app.worker.run(fetch_treasury, self._show, self._failed)

    def _failed(self, error):
        self.asof.configure(text=str(error), fg=DOWN)
        self._message(self.curve_fig, self.curve_canvas, "Treasury data unavailable")
        self._message(self.spread_fig, self.spread_canvas, "")

    @staticmethod
    def _message(fig, canvas, text):
        fig.clear()
        fig.text(0.5, 0.5, text, ha="center", va="center", color=FAINT, fontsize=11)
        canvas.draw_idle()

    def _show(self, df):
        latest = df.iloc[-1]
        prior = df.iloc[-2] if len(df) > 1 else latest
        date = latest["Date"]

        def row_before(days):
            older = df[df["Date"] <= date - pd.Timedelta(days=days)]
            return older.iloc[-1] if not older.empty else None

        month_ago, year_ago = row_before(30), row_before(365)
        self.asof.configure(text=f"As of {short_date(date)}  ·  Source: U.S. Department of the Treasury",
                            fg=FAINT)

        # signal cards
        def bp(a, b):
            return (float(a) - float(b)) * 100

        def fill_signal(key, value_text, sub_text, sub_color, badge=None):
            value, sub = self.signals[key]
            value.configure(text=value_text)
            for w in sub.winfo_children():
                w.destroy()
            if badge:
                good = badge == "Normal"
                b = label(sub, badge.upper(), "eyebrow", fg=UP if good else DOWN,
                          bg=UP_SOFT if good else DOWN_SOFT, padx=S(8), pady=S(2))
                b.pack(side="left", padx=(0, S(8)))
            label(sub, sub_text, "small", fg=sub_color).pack(side="left")

        for key, col in (("10-Year Yield", "10 Yr"), ("2-Year Yield", "2 Yr")):
            change = bp(latest[col], prior[col])
            fill_signal(key, f"{float(latest[col]):.2f}%", f"{change:+.0f} bp on the day", trend_color(change))
        for key, short in (("2s10s Spread", "2 Yr"), ("3M–10Y Spread", "3 Mo")):
            spread = bp(latest["10 Yr"], latest[short])
            change = spread - bp(prior["10 Yr"], prior[short])
            fill_signal(key, f"{spread:+.0f} bp", f"{change:+.0f} bp on the day", MUTED,
                        badge="Normal" if spread >= 0 else "Inverted")

        self._draw_curve(latest, month_ago, year_ago)
        self._fill_table(latest, month_ago, year_ago)
        self._draw_spreads(df)

        s2 = bp(latest["10 Yr"], latest["2 Yr"])
        s3 = bp(latest["10 Yr"], latest["3 Mo"])
        shape = ("upward sloping" if s2 > 25 and s3 > 25 else
                 "inverted" if s2 < 0 and s3 < 0 else "fairly flat")
        self.summary.configure(
            text=f"The curve is {shape}. The 10-year Treasury yields {float(latest['10 Yr']):.2f}%, "
                 f"{abs(s2):.0f} bp {'above' if s2 >= 0 else 'below'} the 2-year and "
                 f"{abs(s3):.0f} bp {'above' if s3 >= 0 else 'below'} the 3-month bill.")

    def _curve_points(self, row):
        xs, ys = [], []
        if row is None:
            return xs, ys
        for i, (_, col) in enumerate(MATURITIES):
            if col in row and not pd.isna(row[col]):
                xs.append(i)
                ys.append(float(row[col]))
        return xs, ys

    def _draw_curve(self, latest, month_ago, year_ago):
        fig = self.curve_fig
        fig.clear()
        ax = fig.add_subplot(111)
        style_axes(ax)
        for row, name, color, style, width in ((year_ago, "1 year ago", FAINT, ":", 1.4),
                                               (month_ago, "1 month ago", ACCENT, "--", 1.4),
                                               (latest, "Today", INK, "-", 2.2)):
            xs, ys = self._curve_points(row)
            if not xs:
                continue
            when = f"{name} ({short_date(row['Date'])})"
            ax.plot(xs, ys, linestyle=style, color=color, linewidth=width, label=when,
                    marker="o", markersize=5 if name == "Today" else 3.5, markerfacecolor=color,
                    markeredgecolor=BG)
            if name == "Today":
                for x, y in zip(xs, ys):
                    ax.annotate(f"{y:.2f}", (x, y), textcoords="offset points", xytext=(0, 8),
                                ha="center", fontsize=7.5, color=MUTED)
        ax.set_xticks(range(len(MATURITIES)))
        ax.set_xticklabels([m for m, _ in MATURITIES])
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:.1f}%"))
        ax.margins(x=0.03, y=0.18)
        ax.legend(loc="lower right", frameon=False, fontsize=8, labelcolor=MUTED)
        fig.subplots_adjust(left=0.07, right=0.99, top=0.95, bottom=0.1)
        self.curve_canvas.draw_idle()

    def _fill_table(self, latest, month_ago, year_ago):
        for w in self.table.winfo_children():
            w.destroy()
        grid = tk.Frame(self.table, bg=SURFACE)
        grid.pack(fill="x")
        for i in range(4):
            grid.columnconfigure(i, weight=1)
        for i, h in enumerate(("", "TODAY", "1M CHG", "1Y CHG")):
            label(grid, h, "eyebrow", fg=FAINT).grid(row=0, column=i, sticky="w" if i == 0 else "e", pady=(0, S(6)))
        for r, (name, col) in enumerate(MATURITIES, start=1):
            now = latest.get(col)
            if pd.isna(now):
                continue
            label(grid, name, "small_semi").grid(row=r, column=0, sticky="w", pady=S(3))
            label(grid, f"{float(now):.2f}%", "small").grid(row=r, column=1, sticky="e")
            for c, past in ((2, month_ago), (3, year_ago)):
                if past is None or pd.isna(past.get(col)):
                    continue
                d = (float(now) - float(past[col])) * 100
                label(grid, f"{d:+.0f} bp", "small", fg=trend_color(d)).grid(row=r, column=c, sticky="e")

    def _draw_spreads(self, df):
        fig = self.spread_fig
        fig.clear()
        ax = fig.add_subplot(111)
        style_axes(ax)
        s2 = (df["10 Yr"] - df["2 Yr"]) * 100
        s3 = (df["10 Yr"] - df["3 Mo"]) * 100
        ax.axhline(0, color=MUTED, linewidth=0.9)
        ax.fill_between(df["Date"], s2, 0, where=s2 < 0, color=DOWN, alpha=0.12, linewidth=0, interpolate=True)
        ax.fill_between(df["Date"], s2, 0, where=s2 >= 0, color=UP, alpha=0.08, linewidth=0, interpolate=True)
        ax.plot(df["Date"], s2, color=INK, linewidth=1.6, label="10Y – 2Y")
        ax.plot(df["Date"], s3, color=ACCENT, linewidth=1.3, label="10Y – 3M")
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:+.0f} bp"))
        ax.xaxis.set_major_formatter(DateFormatter("%b '%y"))
        ax.margins(x=0.01)
        ax.legend(loc="upper left", frameon=False, fontsize=8, ncol=2, labelcolor=MUTED)
        fig.subplots_adjust(left=0.07, right=0.99, top=0.95, bottom=0.12)
        self.spread_canvas.draw_idle()


# -----------------------------------------------------------------------------
# 9. The application window
# -----------------------------------------------------------------------------
class App(tk.Tk):
    PAGES = [("Home", HomePage), ("Markets", MarketsPage), ("News", NewsPage),
             ("Watchlist", WatchlistPage), ("Bond Market", BondPage)]

    def __init__(self):
        global SCALE
        super().__init__()
        SCALE = self.winfo_fpixels("1i") / 96
        self.title(APP_NAME)
        self.configure(bg=BG)
        self._size_window()
        self._set_icon()
        init_fonts(self)
        init_ttk(self)

        self.worker = Worker(self)
        self.watchlist = WatchlistStore()
        self._articles, self._article_waiters, self._articles_loading = None, [], False

        self._build_header()
        self._build_footer()
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)

        self.pages = {name: cls(self) for name, cls in self.PAGES}
        self.current = None
        self.show("Home")

        self.bind_all("<MouseWheel>", self._on_wheel)
        for i, (name, _) in enumerate(self.PAGES, start=1):
            self.bind_all(f"<Control-Key-{i}>", lambda e, n=name: self.show(n))
        self.bind_all("<Control-f>", lambda e: self._focus_search())
        self._tick()

    # --- window setup -----------------------------------------------------------
    def _size_window(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(S(1400), int(sw * 0.92)), min(S(900), int(sh * 0.88))
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max((sh - h) // 2 - S(20), 0)}")
        self.minsize(min(S(1100), w), min(S(680), h))

    def _set_icon(self):
        ico = resource_path("icon.ico")
        try:
            if sys.platform == "win32" and os.path.exists(ico):
                self.iconbitmap(default=ico)
                return
            img = Image.open(resource_path("assets", "icon.png"))
            img.thumbnail((128, 128))
            self._icon = ImageTk.PhotoImage(img)
            self.iconphoto(True, self._icon)
        except Exception as exc:
            print(f"Couldn't set icon: {exc}")

    def _build_header(self):
        header = tk.Frame(self, bg=BG)
        header.pack(fill="x")
        bar = tk.Frame(header, bg=BG)
        bar.pack(fill="x", padx=S(40), pady=S(14))
        bar.columnconfigure(0, weight=1, uniform="sides")
        bar.columnconfigure(2, weight=1, uniform="sides")

        # logo — flattened onto the cream background so it blends into the header
        try:
            logo = Image.open(resource_path("assets", "logo.png")).convert("RGBA")
            logo = Image.alpha_composite(Image.new("RGBA", logo.size, BG), logo).convert("RGB")
            h = S(46)
            logo = logo.resize((int(logo.width * h / logo.height), h), Image.LANCZOS)
            self._logo = ImageTk.PhotoImage(logo)
            brand = tk.Label(bar, image=self._logo, bg=BG, cursor="hand2")
        except Exception:
            brand = label(bar, APP_NAME, "h2", cursor="hand2")
        brand.grid(row=0, column=0, sticky="w")
        brand.bind("<Button-1>", lambda e: self.show("Home"))

        nav = tk.Frame(bar, bg=BG)
        nav.grid(row=0, column=1)
        self.nav_links = {}
        for name, _ in self.PAGES:
            link = label(nav, name, "nav", cursor="hand2")
            link.pack(side="left", padx=S(18))
            link.bind("<Button-1>", lambda e, n=name: self.show(n))
            link.bind("<Enter>", lambda e, l=link: l.configure(fg=ACCENT))
            link.bind("<Leave>", lambda e, n=name, l=link: l.configure(fg=ACCENT if n == self.current else INK))
            self.nav_links[name] = link

        right = tk.Frame(bar, bg=BG)
        right.grid(row=0, column=2, sticky="e")
        RoundButton(right, "Subscribe", lambda: open_link(SITE_URL), radius=12).pack(side="right")
        divider(header)

    def _build_footer(self):
        # packed before the page body (side="bottom") so it always stays visible
        footer = tk.Frame(self, bg=BG)
        footer.pack(fill="x", side="bottom")
        tk.Frame(self, bg=BORDER, height=1).pack(fill="x", side="bottom")
        inner = tk.Frame(footer, bg=BG)
        inner.pack(fill="x", padx=S(40), pady=S(10))
        self.market_dot = tk.Canvas(inner, width=S(8), height=S(8), bg=BG, highlightthickness=0)
        self.market_dot.pack(side="left", padx=(0, S(8)))
        self.market_label = label(inner, "", "small", fg=MUTED)
        self.market_label.pack(side="left")
        self.status_label = label(inner, "", "small", fg=FAINT)
        self.status_label.pack(side="left", padx=S(24))
        self.clock_label = label(inner, "", "small_semi")
        self.clock_label.pack(side="right")
        contact = label(inner, f"© {datetime.now().year} The Milton Review  ·  Not financial advice  ·  "
                               f"{CONTACT_EMAIL}", "small", fg=FAINT, cursor="hand2")
        contact.pack(side="right", padx=S(24))
        contact.bind("<Button-1>", lambda e: open_link(f"mailto:{CONTACT_EMAIL}"))

    # --- navigation ---------------------------------------------------------------
    def show(self, name):
        if name == self.current:
            return
        if self.current:
            self.pages[self.current].hide()
            self.pages[self.current].pack_forget()
        self.current = name
        self.set_status("")
        page = self.pages[name]
        page.pack(fill="both", expand=True)
        page.show()
        for n, link in self.nav_links.items():
            link.configure(fg=ACCENT if n == name else INK,
                           font=FONTS["nav_active"] if n == name else FONTS["nav"])

    def open_symbol(self, symbol):
        self.show("Markets")
        self.pages["Markets"].load(symbol)

    def _focus_search(self):
        page = self.pages[self.current]
        target = getattr(page, "search", None) or getattr(page, "entry", None)
        if target:
            target.focus()

    def set_status(self, text):
        self.status_label.configure(text=text)

    # --- shared data ----------------------------------------------------------------
    def get_articles(self, on_done, on_error=None):
        """Milton Review posts are shared by the Home and News pages; fetch them once."""
        if self._articles is not None:
            on_done(self._articles)
            return
        self._article_waiters.append((on_done, on_error))
        if self._articles_loading:
            return
        self._articles_loading = True

        def done(articles):
            self._articles, self._articles_loading = articles, False
            waiters, self._article_waiters = self._article_waiters, []
            for cb, _ in waiters:
                cb(articles)

        def failed(error):
            self._articles_loading = False
            waiters, self._article_waiters = self._article_waiters, []
            for _, cb in waiters:
                if cb:
                    cb(error)

        self.worker.run(fetch_milton_articles, done, failed)

    # --- events -----------------------------------------------------------------------
    def _on_wheel(self, event):
        try:
            widget = self.winfo_containing(event.x_root, event.y_root)
        except (KeyError, tk.TclError):
            return
        while widget is not None and not isinstance(widget, ScrollFrame):
            widget = widget.master
        if widget is not None:
            widget.scroll(event)

    def _tick(self):
        """Footer clock + market status, once a second."""
        now = datetime.now()
        self.clock_label.configure(text=now.strftime("%A, %B %d, %Y").replace(" 0", " ")
                                   + "   " + clock_time(now, seconds=True))
        is_open, text = market_status()
        self.market_label.configure(text=text)
        self.market_dot.delete("all")
        self.market_dot.create_oval(0, 0, S(7), S(7), fill=UP if is_open else ACCENT, outline="")
        if now.second == 0 or not hasattr(self, "_ticked"):
            self._ticked = True
            self.pages["Home"].update_status()
        self.after(1000, self._tick)


def main():
    if sys.platform == "win32":
        try:  # crisp text on high-DPI screens
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:
            pass
    load_bundled_fonts()
    app = App()

    # close the PyInstaller splash screen once the window is ready (only exists inside the EXE)
    try:
        import pyi_splash
        pyi_splash.close()
    except Exception:  # ImportError when run as a script, KeyError in an EXE built without --splash
        pass

    app.mainloop()


if __name__ == "__main__":
    main()
