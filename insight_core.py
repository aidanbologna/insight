# =============================================================================
#  Insight by Milton — shared core
#
#  Everything that fetches, caches, judges or formats market data, plus the brand
#  and content constants. The Windows app (insightByMilton.py) and the web server
#  (web/) both import it, so this file must not import tkinter or matplotlib.
#
#  Data:   Yahoo Finance (yfinance), U.S. Treasury, The Milton Review RSS feed
# =============================================================================

import html
import importlib
import io
import json
import logging
import math
import os
import random
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib import request
from urllib.parse import parse_qs, urlencode, urlparse

try:
    from zoneinfo import ZoneInfo
    EASTERN = ZoneInfo("America/New_York")
except Exception:  # tzdata missing — fall back to local time
    EASTERN = None


# -----------------------------------------------------------------------------
# 1. Brand and content: colours, links, copy and the lists the pages are built from
# -----------------------------------------------------------------------------
THEMES = {
    "light": {
        "BG": "#FDFBF7",          # page cream
        "SURFACE": "#FFFFFF",     # cards
        "SAND": "#F3EFE7",        # soft panels
        "BORDER": "#E6E0D6",      # hairlines
        "INK": "#1C1C1C",         # text
        "MUTED": "#595959",       # secondary text
        "FAINT": "#8C877F",       # tertiary text
        "ACCENT": "#D47A5D",      # Milton terracotta
        "ACCENT_DARK": "#B9603F",
        "ACCENT_SOFT": "#F7E6DF",
        "UP": "#2F7D4F", "UP_SOFT": "#E4F0E7",
        "DOWN": "#B4473A", "DOWN_SOFT": "#F6E2DE",
        "FAIR": "#A0721A", "FAIR_SOFT": "#F8EDD3",   # amber "yellow" that stays readable
    },
    "dark": {
        "BG": "#161513",
        "SURFACE": "#201E1B",
        "SAND": "#2A2723",
        "BORDER": "#3A3631",
        "INK": "#EEE9E1",
        "MUTED": "#B5AEA4",
        "FAINT": "#8B857C",
        "ACCENT": "#E28C6D",
        "ACCENT_DARK": "#C9714F",
        "ACCENT_SOFT": "#3D2A22",
        "UP": "#5DBB82", "UP_SOFT": "#1D3427",
        "DOWN": "#E37C6E", "DOWN_SOFT": "#3D2420",
        "FAIR": "#D9AE52", "FAIR_SOFT": "#3A3020",
    },
}
COLOR_NAMES = ("BG", "SURFACE", "SAND", "BORDER", "INK", "MUTED", "FAINT", "ACCENT", "ACCENT_DARK",
               "ACCENT_SOFT", "UP", "UP_SOFT", "DOWN", "DOWN_SOFT", "FAIR", "FAIR_SOFT")


# Colour themes offered in "Colors & appearance". Each names only the colours it changes from Milton's own;
# the in-between shades (panels, hairlines, secondary text, soft pills) are mixed to match by build_palette().
COLOR_PRESETS = {
    "Milton": {"light": {}, "dark": {}},
    "Ocean": {"light": {"ACCENT": "#2E6F9E", "BG": "#F6F9FC", "SURFACE": "#FFFFFF", "INK": "#16212B"},
              "dark": {"ACCENT": "#6FB1E0", "BG": "#10151A", "SURFACE": "#182028", "INK": "#E6EDF3"}},
    "Forest": {"light": {"ACCENT": "#3C7A57", "BG": "#F7FAF4", "SURFACE": "#FFFFFF", "INK": "#1A211C"},
               "dark": {"ACCENT": "#7CC79A", "BG": "#111612", "SURFACE": "#1A211B", "INK": "#E6EDE5"}},
    "Plum": {"light": {"ACCENT": "#7B4B94", "BG": "#FAF7FB", "SURFACE": "#FFFFFF", "INK": "#201A24"},
             "dark": {"ACCENT": "#C09AD6", "BG": "#151217", "SURFACE": "#1F1A22", "INK": "#ECE6F0"}},
    "Rose": {"light": {"ACCENT": "#C2476D", "BG": "#FDF7F8", "SURFACE": "#FFFFFF", "INK": "#231A1C"},
             "dark": {"ACCENT": "#EC8FAB", "BG": "#171213", "SURFACE": "#221A1C", "INK": "#F0E6E8"}},
    "Gold": {"light": {"ACCENT": "#A8741A", "BG": "#FCFAF3", "SURFACE": "#FFFFFF", "INK": "#211D14"},
             "dark": {"ACCENT": "#E0B354", "BG": "#16140F", "SURFACE": "#201D16", "INK": "#EFE9DA"}},
    "Graphite": {"light": {"ACCENT": "#4A5A6A", "BG": "#F5F6F7", "SURFACE": "#FFFFFF", "INK": "#1B1D1F"},
                 "dark": {"ACCENT": "#A9B8C6", "BG": "#131415", "SURFACE": "#1C1E20", "INK": "#E8EAEC"}},
    "High contrast": {
        "light": {"ACCENT": "#0B4FC4", "BG": "#FFFFFF", "SURFACE": "#FFFFFF", "INK": "#000000", "UP": "#0A6B2D",
                  "DOWN": "#B00020", "BORDER": "#767676", "MUTED": "#333333", "FAINT": "#555555"},
        "dark": {"ACCENT": "#FFD54A", "BG": "#000000", "SURFACE": "#0E0E0E", "INK": "#FFFFFF", "UP": "#5BE38A",
                 "DOWN": "#FF8A7A", "BORDER": "#8A8A8A", "MUTED": "#DDDDDD", "FAINT": "#BBBBBB"}},
}
# Blue for gains and orange for losses stay distinct with red-green colour blindness; "fair" turns grey.
COLORBLIND_UPDOWN = {"light": {"UP": "#0F6CB5", "DOWN": "#C2570A", "FAIR": "#6B6B6B"},
                     "dark": {"UP": "#6DB6F2", "DOWN": "#F2A25C", "FAIR": "#A8A8A8"}}


def is_hex(value):
    """True for colours written like "#D47A5D"."""
    return isinstance(value, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", value) is not None


def blend(color, other, amount):
    """Mix two hex colours; amount=0 gives color, 1 gives other."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def luminance(color):
    """How bright a hex colour looks, from 0 (black) to 1 (white) — WCAG relative luminance."""
    total = 0.0
    for i, weight in ((1, 0.2126), (3, 0.7152), (5, 0.0722)):
        v = int(color[i:i + 2], 16) / 255
        total += weight * (v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4)
    return total


def contrast(a, b):
    """WCAG contrast ratio between two colours: 1 (the same) up to 21 (black on white)."""
    hi, lo = sorted((luminance(a), luminance(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def build_palette(mode, appearance=None):
    """All 16 colours for one mode: Milton's theme with the chosen colour theme, the colour-blind friendly
    gains/losses and any custom colours laid on top. Shades that sit between two colours are re-mixed.

    appearance is the "appearance" entry of settings.json:
        {"preset": "Ocean", "updown": "classic" | "colorblind",
         "custom": {"light": {"ACCENT": "#123ABC", ...}, "dark": {...}}}
    """
    mode = mode if mode in ("light", "dark") else "light"
    appearance = appearance if isinstance(appearance, dict) else {}
    custom = appearance.get("custom")
    custom = custom.get(mode) if isinstance(custom, dict) else None
    custom = {k: v for k, v in custom.items() if k in COLOR_NAMES and is_hex(v)} if isinstance(custom, dict) else {}
    family = mode
    if "BG" in custom:      # a custom background decides whether the light or dark supporting colours are used
        family = "dark" if luminance(custom["BG"]) < 0.2 else "light"
    preset = appearance.get("preset")
    chosen = dict(COLOR_PRESETS.get(preset, {}).get(family, {})) if isinstance(preset, str) else {}
    if appearance.get("updown") == "colorblind":
        chosen.update(COLORBLIND_UPDOWN[family])
    chosen.update(custom)
    base = THEMES[family]
    colors = {**base, **chosen}
    dark = luminance(colors["BG"]) < 0.2

    def card_color():
        return blend(colors["BG"], colors["INK"], 0.045) if dark else blend(colors["BG"], "#FFFFFF", 0.85)

    def mix(name, value):   # re-mix a shade unless it was picked by hand
        if name not in chosen:
            colors[name] = value

    if contrast(colors["INK"], colors["BG"]) < 3:       # whatever was picked, text has to stay readable
        colors["INK"] = base["INK"]
    changed = {name for name in COLOR_NAMES if colors[name].lower() != base[name].lower()}
    if changed & {"BG", "INK"}:
        mix("SURFACE", card_color())
    if contrast(colors["INK"], colors["SURFACE"]) < 3:
        colors["SURFACE"] = card_color()
    if changed & {"BG", "INK"}:
        mix("SAND", blend(colors["BG"], colors["INK"], 0.09 if dark else 0.05))
        mix("BORDER", blend(colors["BG"], colors["INK"], 0.165 if dark else 0.11))
        mix("MUTED", blend(colors["INK"], colors["BG"], 0.27))
        mix("FAINT", blend(colors["INK"], colors["BG"], 0.46 if dark else 0.5))
    if "ACCENT" in changed:
        mix("ACCENT_DARK", blend(colors["ACCENT"], "#000000", 0.16))
    for name in ("ACCENT", "UP", "DOWN", "FAIR"):
        if name in changed or colors["SURFACE"].lower() != base["SURFACE"].lower():
            mix(name + "_SOFT", blend(colors["SURFACE"], colors[name], 0.16))
    return colors


APP_NAME = "Insight by Milton"
SITE_URL = "https://www.themiltonreview.net"
BLOG_URL = SITE_URL + "/blog"
RSS_URL = SITE_URL + "/blog-feed.xml"
CONTACT_EMAIL = "aidanbologna@themiltonreview.net"
RELEASES_URL = "https://github.com/aidanbologna/insight/releases"
SETUP_URL = RELEASES_URL + "/latest/download/InsightByMilton-Setup.exe"    # always the newest installer

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
    "1M": ("10y", "1d", 30),        # 1M–5Y all come from one cached 10-year download,
    "6M": ("10y", "1d", 182),       # so switching between them is instant
    "YTD": ("10y", "1d", "ytd"),
    "1Y": ("10y", "1d", 365),
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

# News outlets. Bias ratings are AllSides Media Bias Ratings, checked on allsides.com in October 2026.
BIAS_SCALE = ["Left", "Lean Left", "Center", "Lean Right", "Right"]
BIAS_COLORS = {"Left": "#2F5C9E", "Lean Left": "#6E98CF", "Center": "#8E79AE",
               "Lean Right": "#D98A84", "Right": "#B23A35"}
BIAS_MEANING = {
    "Left": "Coverage shows a strong, consistent left-of-center perspective in which stories are "
            "chosen and how they are framed.",
    "Lean Left": "Coverage shows a mild left-of-center tilt — mostly straight news, with story choice "
                 "and wording that lean slightly left.",
    "Center": "Coverage doesn't show much predictable political bias, or its leanings balance out "
              "across stories.",
    "Lean Right": "Coverage shows a mild right-of-center tilt — mostly straight news, with story choice "
                  "and wording that lean slightly right.",
    "Right": "Coverage shows a strong, consistent right-of-center perspective in which stories are "
             "chosen and how they are framed.",
}
ALLSIDES = "https://www.allsides.com/news-source/"

NEWS_SOURCES = [
    {"id": "cnbc", "name": "CNBC", "short": "CNBC", "color": "#005594", "bias": "Lean Left",
     "site": "https://www.cnbc.com", "allsides": ALLSIDES + "cnbc",
     "feeds": ["https://www.cnbc.com/id/100003114/device/rss/rss.html",
               "https://www.cnbc.com/id/15839069/device/rss/rss.html"],
     "facts": {"Founded": "1989", "Headquarters": "Englewood Cliffs, New Jersey", "Focus": "Business TV & markets"},
     "about": "CNBC is a business news network best known for live coverage of the trading day, with "
              "shows such as Squawk Box and Mad Money. Its website covers markets, investing, the "
              "economy and corporate news around the clock."},
    {"id": "wsj", "name": "The Wall Street Journal", "short": "WSJ", "color": "#222222", "bias": "Center",
     "site": "https://www.wsj.com", "allsides": ALLSIDES + "wall-street-journal-media-bias",
     "feeds": ["https://feeds.content.dowjones.io/public/rss/RSSMarketsMain"],
     "facts": {"Founded": "1889", "Owner": "Dow Jones & Company (News Corp)", "Headquarters": "New York City",
               "Focus": "Business, markets & politics"},
     "about": "The Wall Street Journal is one of the largest U.S. newspapers and a leading source of business "
              "and financial reporting. AllSides rates its news section; its opinion pages are rated "
              "separately. Many articles require a subscription."},
    {"id": "marketwatch", "name": "MarketWatch", "short": "MW", "color": "#4C8C2B", "bias": "Center",
     "site": "https://www.marketwatch.com", "allsides": ALLSIDES + "marketwatch-media-bias",
     "feeds": ["https://feeds.content.dowjones.io/public/rss/mw_topstories"],
     "facts": {"Founded": "1997", "Owner": "Dow Jones & Company (News Corp)", "Headquarters": "New York City",
               "Focus": "Markets & personal finance"},
     "about": "MarketWatch publishes market news, stock data and personal-finance advice. It began as a "
              "joint venture between Data Broadcasting Corp. and CBS and has been part of Dow Jones, "
              "publisher of The Wall Street Journal, since 2005."},
    {"id": "bloomberg", "name": "Bloomberg", "short": "BBG", "color": "#3A2AD1", "bias": "Center",
     "site": "https://www.bloomberg.com", "allsides": ALLSIDES + "bloomberg",
     "feeds": ["https://feeds.bloomberg.com/markets/news.rss"],
     "facts": {"Founded": "1990 (news service)", "Owner": "Bloomberg L.P.", "Headquarters": "New York City",
               "Focus": "Global markets & finance"},
     "about": "Bloomberg News is the newsroom of Bloomberg L.P., the financial data company behind the "
              "Bloomberg Terminal used across Wall Street. It reports on markets, companies and economies "
              "worldwide. Many articles require a subscription."},
    {"id": "ft", "name": "Financial Times", "short": "FT", "color": "#990F3D", "bias": "Center",
     "site": "https://www.ft.com", "allsides": ALLSIDES + "financial-times-media-bias",
     "feeds": ["https://www.ft.com/markets?format=rss"],
     "facts": {"Founded": "1888", "Owner": "Nikkei Inc.", "Headquarters": "London",
               "Focus": "International business & economics"},
     "about": "The Financial Times is a London-based daily known for its salmon-pink print edition and "
              "in-depth coverage of global business, markets and economic policy. It has been owned by "
              "Japan's Nikkei since 2015. Most articles require a subscription."},
    {"id": "economist", "name": "The Economist", "short": "ECON", "color": "#E3120B", "bias": "Lean Left",
     "site": "https://www.economist.com", "allsides": ALLSIDES + "economist",
     "feeds": ["https://www.economist.com/finance-and-economics/rss.xml"],
     "facts": {"Founded": "1843", "Owner": "The Economist Group", "Headquarters": "London",
               "Focus": "Economics, politics & world affairs"},
     "about": "The Economist is a weekly magazine covering economics, politics, business and science from "
              "a global perspective. Its articles are famously unsigned, written in a single house voice. "
              "Most articles require a subscription."},
    {"id": "bbc", "name": "BBC News", "short": "BBC", "color": "#B80000", "bias": "Center",
     "site": "https://www.bbc.com/business", "allsides": ALLSIDES + "bbc-news-media-bias",
     "feeds": ["https://feeds.bbci.co.uk/news/business/rss.xml"],
     "facts": {"Founded": "1922", "Owner": "British Broadcasting Corporation (public)",
               "Headquarters": "London", "Focus": "World & UK news"},
     "about": "BBC News is the news division of the United Kingdom's public broadcaster, funded mainly by "
              "the UK licence fee. Its business desk covers global markets, companies and the economy, "
              "with a strong international and British focus."},
    {"id": "nyt", "name": "The New York Times", "short": "NYT", "color": "#121212", "bias": "Lean Left",
     "site": "https://www.nytimes.com/section/business", "allsides": ALLSIDES + "new-york-times",
     "feeds": ["https://rss.nytimes.com/services/xml/rss/nyt/Business.xml"],
     "facts": {"Founded": "1851", "Owner": "The New York Times Company", "Headquarters": "New York City",
               "Focus": "National & world news"},
     "about": "The New York Times is one of the most widely read U.S. newspapers. Its business section "
              "covers the economy, Wall Street, technology and media, alongside its DealBook newsletter. "
              "Many articles require a subscription."},
    {"id": "guardian", "name": "The Guardian", "short": "GDN", "color": "#052962", "bias": "Left",
     "site": "https://www.theguardian.com/business", "allsides": ALLSIDES + "guardian",
     "feeds": ["https://www.theguardian.com/business/rss"],
     "facts": {"Founded": "1821", "Owner": "Scott Trust Limited", "Headquarters": "London",
               "Focus": "World news & commentary"},
     "about": "The Guardian is a British daily founded in Manchester. It is owned by the Scott Trust, "
              "which exists to protect its editorial independence, and it keeps its website free to read, "
              "funded largely by reader contributions."},
    {"id": "npr", "name": "NPR", "short": "NPR", "color": "#2F62B8", "bias": "Lean Left",
     "site": "https://www.npr.org/sections/economy", "allsides": ALLSIDES + "npr-editorial",
     "feeds": ["https://feeds.npr.org/1017/rss.xml"],
     "facts": {"Founded": "1970", "Owner": "Nonprofit membership organization",
               "Headquarters": "Washington, D.C.", "Focus": "Public radio news"},
     "about": "NPR (National Public Radio) is a nonprofit media organization that produces news programs "
              "such as Morning Edition and All Things Considered for a network of public radio stations. "
              "Its economy coverage is free to read."},
    {"id": "forbes", "name": "Forbes", "short": "FRBS", "color": "#3C3C3C", "bias": "Center",
     "site": "https://www.forbes.com", "allsides": ALLSIDES + "forbes",
     "feeds": ["https://www.forbes.com/business/feed/"],
     "facts": {"Founded": "1917", "Headquarters": "Jersey City, New Jersey",
               "Focus": "Business, wealth & entrepreneurship"},
     "about": "Forbes is a business magazine famous for its billionaires and richest-people lists. Its "
              "website mixes staff reporting with a large network of outside contributors, so quality and "
              "viewpoint can vary from article to article."},
    {"id": "thehill", "name": "The Hill", "short": "HILL", "color": "#1F3B5A", "bias": "Center",
     "site": "https://thehill.com/business", "allsides": ALLSIDES + "hill",
     "feeds": ["https://thehill.com/business/feed/"],
     "facts": {"Founded": "1994", "Owner": "Nexstar Media Group", "Headquarters": "Washington, D.C.",
               "Focus": "Congress, policy & politics"},
     "about": "The Hill is a Washington publication focused on Congress, the White House and policy. Its "
              "business coverage leans toward how government decisions — taxes, regulation, trade — "
              "affect the economy and markets."},
    {"id": "foxbusiness", "name": "Fox Business", "short": "FOXB", "color": "#003F7D", "bias": "Lean Right",
     "site": "https://www.foxbusiness.com", "allsides": ALLSIDES + "fox-business-media-bias",
     "feeds": ["https://moxie.foxbusiness.com/google-publisher/economy.xml",
               "https://moxie.foxbusiness.com/google-publisher/markets.xml"],
     "facts": {"Founded": "2007", "Owner": "Fox Corporation", "Headquarters": "New York City",
               "Focus": "Business TV, markets & economy"},
     "about": "Fox Business Network is a business news channel and website from Fox Corporation, the "
              "parent of Fox News. It covers markets, the economy, personal finance and economic policy."},
    {"id": "nypost", "name": "New York Post", "short": "POST", "color": "#C8102E", "bias": "Right",
     "site": "https://nypost.com/business", "allsides": ALLSIDES + "new-york-post",
     "feeds": ["https://nypost.com/business/feed/"],
     "facts": {"Founded": "1801", "Owner": "News Corp", "Headquarters": "New York City",
               "Focus": "Tabloid news & business"},
     "about": "The New York Post is one of America's oldest newspapers, founded by Alexander Hamilton. "
              "Today it is a tabloid known for punchy headlines; its business section covers Wall Street, "
              "retail, media and real estate."},
    {"id": "examiner", "name": "Washington Examiner", "short": "WE", "color": "#9E1B22", "bias": "Lean Right",
     "site": "https://www.washingtonexaminer.com", "allsides": ALLSIDES + "washington-examiner",
     "feeds": ["https://www.washingtonexaminer.com/tag/economy/feed/"],
     "facts": {"Founded": "2005", "Owner": "Clarity Media Group", "Headquarters": "Washington, D.C.",
               "Focus": "Politics & policy"},
     "about": "The Washington Examiner is a Washington-based news and opinion outlet covering politics, "
              "policy and the economy, publishing online and as a magazine."},
    {"id": "wtimes", "name": "The Washington Times", "short": "WT", "color": "#1C3F6E", "bias": "Lean Right",
     "site": "https://www.washingtontimes.com", "allsides": ALLSIDES + "washington-times",
     "feeds": ["https://www.washingtontimes.com/rss/headlines/news/business-economy/"],
     "facts": {"Founded": "1982", "Headquarters": "Washington, D.C.", "Focus": "National politics & policy"},
     "about": "The Washington Times is a daily newspaper in the nation's capital founded in 1982 by "
              "businesses tied to the Unification Church. It covers national politics, security and the "
              "economy."},
]
NEWS_SOURCES += [
    {"id": "insider", "name": "Business Insider", "short": "BI", "color": "#1C5DB3", "bias": "Lean Left",
     "site": "https://www.businessinsider.com", "allsides": ALLSIDES + "business-insider", "finance_only": True,
     "feeds": ["https://feeds.businessinsider.com/custom/all"],
     "facts": {"Founded": "2007", "Owner": "Axel Springer", "Headquarters": "New York City",
               "Focus": "Business, tech & finance"},
     "about": "Business Insider began in 2007 as the tech blog Silicon Alley Insider and grew into a large "
              "digital outlet covering business, markets, technology and careers. It has been owned by "
              "Germany's Axel Springer since 2015. Only its finance and business stories are shown here."},
    {"id": "cbs", "name": "CBS News MoneyWatch", "short": "CBS", "color": "#1F2A44", "bias": "Lean Left",
     "site": "https://www.cbsnews.com/moneywatch/", "allsides": ALLSIDES + "cbs-news",
     "feeds": ["https://www.cbsnews.com/latest/rss/moneywatch"],
     "facts": {"Headquarters": "New York City", "Focus": "Consumer finance & the economy"},
     "about": "MoneyWatch is the business and personal-finance desk of CBS News, one of the original "
              "American broadcast networks. It focuses on how the economy, prices, jobs and companies affect "
              "everyday households."},
    {"id": "fortune", "name": "Fortune", "short": "FORT", "color": "#C8102E", "bias": "Center",
     "site": "https://fortune.com", "allsides": ALLSIDES + "fortune",
     "feeds": ["https://fortune.com/feed/"],
     "facts": {"Founded": "1930", "Headquarters": "New York City", "Focus": "Business & leadership"},
     "about": "Fortune is a business magazine founded by Henry Luce in 1930, best known for the Fortune 500 "
              "ranking of America's largest companies. It covers corporate strategy, leadership, finance "
              "and the economy."},
    {"id": "quartz", "name": "Quartz", "short": "QZ", "color": "#2B2B2B", "bias": "Center",
     "site": "https://qz.com", "allsides": ALLSIDES + "quartz", "finance_only": True,
     "feeds": ["https://qz.com/rss"],
     "facts": {"Founded": "2012", "Headquarters": "New York City", "Focus": "Global business & economics"},
     "about": "Quartz is a digital business news outlet launched in 2012 by Atlantic Media, known for "
              "short, chart-heavy explainers about the global economy, markets and companies."},
    {"id": "reason", "name": "Reason", "short": "RSN", "color": "#E2571E", "bias": "Center",
     "site": "https://reason.com", "allsides": ALLSIDES + "reason", "finance_only": True,
     "feeds": ["https://reason.com/latest/feed/"],
     "facts": {"Founded": "1968", "Publisher": "Reason Foundation (nonprofit)",
               "Focus": "Libertarian policy & economics"},
     "about": "Reason is a libertarian magazine published by the nonprofit Reason Foundation under the "
              "motto “Free Minds and Free Markets.” It argues for limited government and free markets. "
              "Only its economics and business stories are shown here."},
    {"id": "ibd", "name": "Investor's Business Daily", "short": "IBD", "color": "#00426A",
     "bias": "Lean Right", "site": "https://www.investors.com", "allsides": ALLSIDES + "investors-business-daily",
     "feeds": ["https://www.investors.com/feed/"],
     "facts": {"Founded": "1984", "Owner": "News Corp (Dow Jones)", "Headquarters": "Los Angeles",
               "Focus": "Stocks & investing strategy"},
     "about": "Investor's Business Daily was founded by investor William O'Neil in 1984 and is built around "
              "his CAN SLIM stock-picking method. It covers stock market action, earnings and chart "
              "analysis for active investors."},
    {"id": "breitbart", "name": "Breitbart News", "short": "BRBT", "color": "#D95A00", "bias": "Right",
     "site": "https://www.breitbart.com/economy/", "allsides": ALLSIDES + "breitbart-news-media-bias",
     "feeds": ["https://www.breitbart.com/economy/feed/"],
     "facts": {"Founded": "2007", "Focus": "Conservative news & commentary"},
     "about": "Breitbart News is a conservative news and opinion website founded by Andrew Breitbart in "
              "2007. The stories shown here come from its economy section."},
    {"id": "signal", "name": "The Daily Signal", "short": "SGNL", "color": "#9A1B1F", "bias": "Right",
     "site": "https://www.dailysignal.com", "allsides": ALLSIDES + "daily-signal",
     "feeds": ["https://www.dailysignal.com/category/economy/feed/"],
     "facts": {"Founded": "2014", "Headquarters": "Washington, D.C.", "Focus": "Conservative policy news"},
     "about": "The Daily Signal is a conservative news site launched in 2014 by The Heritage Foundation, a "
              "Washington think tank. The stories shown here come from its economy section."},
]
# Reading access by outlet: free, limited (a few free articles a month) or paywall (subscription).
OUTLET_ACCESS = {"cnbc": "free", "wsj": "paywall", "marketwatch": "limited", "bloomberg": "paywall",
                 "ft": "paywall", "economist": "paywall", "bbc": "free", "nyt": "paywall", "guardian": "free",
                 "npr": "free", "forbes": "limited", "thehill": "free", "foxbusiness": "free", "nypost": "free",
                 "examiner": "free", "wtimes": "free", "insider": "limited", "cbs": "free", "fortune": "limited",
                 "quartz": "free", "reason": "free", "ibd": "limited", "breitbart": "free", "signal": "free"}
for _src in NEWS_SOURCES:
    _src["access"] = OUTLET_ACCESS.get(_src["id"])
SOURCES_BY_ID = {src["id"]: src for src in NEWS_SOURCES}
SOURCE_DOMAINS = {urlparse(src["site"]).netloc.replace("www.", ""): src["id"] for src in NEWS_SOURCES}
SOURCE_DOMAINS.update({"bbc.co.uk": "bbc", "feeds.bbci.co.uk": "bbc", "markets.businessinsider.com": "insider"})
# Other websites that show up in a stock's headlines
DOMAIN_ACCESS = {"barrons.com": "paywall", "washingtonpost.com": "paywall", "theinformation.com": "paywall",
                 "seekingalpha.com": "limited", "tipranks.com": "limited", "morningstar.com": "limited",
                 "latimes.com": "limited", "cnn.com": "limited", "theatlantic.com": "paywall",
                 "kiplinger.com": "limited", "reuters.com": "free", "apnews.com": "free", "axios.com": "free",
                 "fool.com": "free", "finbold.com": "free", "benzinga.com": "free", "zacks.com": "free",
                 "thestreet.com": "free", "investopedia.com": "free", "nasdaq.com": "free", "usatoday.com": "free",
                 "techcrunch.com": "free", "electrek.co": "free", "teslarati.com": "free", "space.com": "free",
                 "cnet.com": "free", "theverge.com": "limited", "fastcompany.com": "limited",
                 "investing.com": "free", "gurufocus.com": "limited", "247wallst.com": "free",
                 "insidermonkey.com": "free", "coindesk.com": "free", "cointelegraph.com": "free",
                 "abcnews.go.com": "free", "nbcnews.com": "free", "politico.com": "free",
                 "dailymail.co.uk": "free", "independent.co.uk": "free", "telegraph.co.uk": "paywall",
                 "thetimes.co.uk": "paywall", "wired.com": "limited", "newsweek.com": "free",
                 "businesswire.com": "free", "prnewswire.com": "free", "globenewswire.com": "free"}

NEWS_TOPICS = {
    "All": [],
    "Markets": ["stock", "stocks", "market", "markets", "s&p", "dow", "nasdaq", "wall street", "shares",
                "investor", "investors", "rally", "sell-off", "selloff", "bond", "treasury", "yields"],
    "Economy": ["economy", "economic", "inflation", "jobs", "gdp", "recession", "unemployment", "tariff",
                "tariffs", "consumer", "wages", "housing", "prices"],
    "The Fed": ["fed", "federal reserve", "powell", "interest rate", "interest rates", "rate cut",
                "rate cuts", "rate hike", "central bank"],
    "Earnings": ["earnings", "revenue", "profit", "profits", "quarter", "quarterly", "guidance", "results"],
    "Tech": ["ai", "tech", "technology", "apple", "microsoft", "nvidia", "google", "alphabet", "amazon",
             "meta", "chip", "chips", "semiconductor", "software", "openai", "tesla"],
    "Energy": ["oil", "gas", "energy", "opec", "crude", "solar", "electricity", "power grid"],
    "Crypto": ["bitcoin", "crypto", "cryptocurrency", "ethereum", "blockchain", "stablecoin", "coinbase"],
}
TOPIC_PATTERNS = {name: re.compile(r"\b(" + "|".join(re.escape(w) for w in words) + r")\b", re.I)
                  for name, words in NEWS_TOPICS.items() if words}

# Words that mark a headline as finance / business news (used for a stock's related articles)
FINANCE_PATTERN = re.compile(
    r"\b(stocks?|shares?|shareholders?|investors?|investing|investments?|markets?|wall street|nasdaq|"
    r"s&p|dow|earnings|revenues?|sales|profits?|losses|quarter|quarterly|guidance|forecasts?|outlook|"
    r"analysts?|price targets?|upgrades?|downgrades?|valuations?|market cap|dividends?|buybacks?|ipo|"
    r"mergers?|acquisitions?|acquires?|acquired|takeover|deal|stake|funds?|trading|traders?|rall(y|ies|ied)|"
    r"sell-?off|plunges?|plunged|surges?|surged|soars?|soared|tumbles?|tumbled|slumps?|slumped|bonds?|"
    r"debt|loans?|banks?|billion|trillion|tariffs?|inflation|economy|economic|fed|interest rates?|"
    r"layoffs?|job cuts|costs?|pricing|prices|cash|capital|financ\w*|sec|antitrust|settlement|"
    r"subscribers|demand|orders|shipments|deliveries|raises?|raised|funding|valued|bitcoin|crypto)\b", re.I)

# Markets overview
INDEXES = [("S&P 500", "^GSPC"), ("Dow Jones", "^DJI"), ("Nasdaq", "^IXIC"), ("Russell 2000", "^RUT")]
SECTORS = [("Technology", "XLK"), ("Financials", "XLF"), ("Health Care", "XLV"),
           ("Consumer Discretionary", "XLY"), ("Communication Services", "XLC"), ("Industrials", "XLI"),
           ("Consumer Staples", "XLP"), ("Energy", "XLE"), ("Utilities", "XLU"),
           ("Real Estate", "XLRE"), ("Materials", "XLB")]
BIG_STOCKS = [("AAPL", "Apple"), ("MSFT", "Microsoft"), ("NVDA", "Nvidia"), ("GOOGL", "Alphabet"),
              ("AMZN", "Amazon"), ("META", "Meta Platforms"), ("AVGO", "Broadcom"), ("TSLA", "Tesla"),
              ("BRK-B", "Berkshire Hathaway"), ("JPM", "JPMorgan Chase"), ("LLY", "Eli Lilly"),
              ("V", "Visa"), ("WMT", "Walmart"), ("XOM", "Exxon Mobil"), ("MA", "Mastercard"),
              ("NFLX", "Netflix"), ("COST", "Costco"), ("UNH", "UnitedHealth")]
OVERVIEW_RANGES = {"1D": ("1d", "5m"), "5D": ("5d", "30m"), "1M": ("1mo", "1d"), "6M": ("6mo", "1d"),
                   "YTD": ("ytd", "1d"), "1Y": ("1y", "1d"), "5Y": ("5y", "1wk")}
TICK_FORMATS = {"1D": "%I:%M %p", "5D": "%a %d", "1M": "%b %d", "6M": "%b %d", "YTD": "%b %d",
                "1Y": "%b '%y", "5Y": "%Y", "MAX": "%Y"}

# Treasury par yield curve maturities: (short label, CSV column)
MATURITIES = [("1M", "1 Mo"), ("3M", "3 Mo"), ("6M", "6 Mo"), ("1Y", "1 Yr"), ("2Y", "2 Yr"),
              ("3Y", "3 Yr"), ("5Y", "5 Yr"), ("7Y", "7 Yr"), ("10Y", "10 Yr"), ("20Y", "20 Yr"),
              ("30Y", "30 Yr")]
TREASURY_URL = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/"
                "daily-treasury-rates.csv/{year}/all?type=daily_treasury_yield_curve"
                "&field_tdr_date_value={year}&page&_format=csv")


class LazyModule:
    """Imports a heavy library the first time it's used so the window can open ~2 s sooner.
    The first use always happens on a background thread, keeping the UI responsive."""
    _lock = threading.Lock()

    def __init__(self, name):
        self._name, self._module = name, None

    def __getattr__(self, attr):
        if self._module is None:
            with LazyModule._lock:
                if self._module is None:
                    self._module = importlib.import_module(self._name)
        return getattr(self._module, attr)


def _bundle_hint():
    # never called — these plain imports just tell PyInstaller to include the libraries
    import pandas  # noqa: F401
    import yfinance  # noqa: F401


pd = LazyModule("pandas")
yf = LazyModule("yfinance")


# -----------------------------------------------------------------------------
# 2. Where downloaded copies are kept (the app makes the folder; a server never needs it for prices)
# -----------------------------------------------------------------------------
DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "InsightByMilton")
TREASURY_CACHE = os.path.join(DATA_DIR, "treasury_cache.csv")


# -----------------------------------------------------------------------------
# 3. Formatting helpers
# -----------------------------------------------------------------------------
def is_missing(v):
    return v is None or (isinstance(v, float) and math.isnan(v))


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


def tidy_name(name):
    """Yahoo writes some names like "Coca-Cola Company (The)"."""
    name = (name or "").strip()
    return "The " + name[:-6] if name.endswith(" (The)") else name


def fmt_money(v, signed=False, decimals=2):
    if is_missing(v):
        return "—"
    sign = ("+" if v > 0 else "-" if v < 0 else "") if signed else ("-" if v < 0 else "")
    return f"{sign}${abs(v):,.{decimals}f}"


def fmt_change(v):
    return "—" if is_missing(v) else f"{v:+,.2f}"


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


def compose_brief(q):
    """The brief on the Home page: a few plain sentences written from the snapshot quotes."""
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


MEDIA = "{http://search.yahoo.com/mrss/}"
ATOM = "{http://www.w3.org/2005/Atom}"
IMG_RE = re.compile(r"<img[^>]+src=[\"']([^\"']+)", re.I)


def _clean(text):
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def _parse_date(text):
    if not text:
        return None
    try:
        dt = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        try:
            dt = datetime.fromisoformat(text.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _item_image(item):
    for tag in (MEDIA + "content", MEDIA + "thumbnail"):
        for el in item.iter(tag):
            url = el.get("url")
            if url and (el.get("medium") in (None, "image") or "image" in (el.get("type") or "")):
                return url
    enclosure = item.find("enclosure")
    if enclosure is not None and "image" in (enclosure.get("type") or "image"):
        return enclosure.get("url")
    raw = (item.findtext("description") or "") + (item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "")
    match = IMG_RE.search(raw)
    return html.unescape(match.group(1)) if match else None


def parse_feed(data, source_id, limit=30):
    root = ET.fromstring(data)
    items = root.findall(".//item") or root.findall(f".//{ATOM}entry")
    articles = []
    for rank, item in enumerate(items[:limit]):
        link = item.findtext("link") or ""
        if not link.strip():
            atom_link = item.find(ATOM + "link")
            link = atom_link.get("href") if atom_link is not None else ""
        title = _clean(item.findtext("title") or item.findtext(ATOM + "title"))
        if not title or not link.strip():
            continue
        summary = _clean(item.findtext("description") or item.findtext(ATOM + "summary"))
        articles.append({
            "source": source_id, "rank": rank, "title": title, "link": link.strip(),
            "summary": summary if summary.lower() != title.lower() else "",
            "date": _parse_date(item.findtext("pubDate") or item.findtext(ATOM + "updated")
                                or item.findtext(ATOM + "published")
                                or item.findtext("{http://purl.org/dc/elements/1.1/}date")),
            "image": _item_image(item),
        })
    return articles


def fetch_source(source):
    """All articles from one outlet's feeds, de-duplicated, in the outlet's own order."""
    articles, seen = [], set()
    for url in source["feeds"]:
        try:
            for art in parse_feed(http_get(url, timeout=10), source["id"]):
                if source.get("finance_only") and not FINANCE_PATTERN.search(art["title"] + " " + art["summary"]):
                    continue    # general-interest outlets: keep only their business stories
                if art["link"] not in seen and art["title"] not in seen:
                    seen.update((art["link"], art["title"]))
                    articles.append(art)
        except Exception as exc:
            print(f"Feed failed ({source['name']}): {exc}")
    return articles


def fetch_all_news():
    """Every outlet's feed, downloaded in parallel. Returns {source id: [articles]}."""
    with ThreadPoolExecutor(max_workers=len(NEWS_SOURCES)) as pool:
        results = pool.map(fetch_source, NEWS_SOURCES)
    news = {src["id"]: arts for src, arts in zip(NEWS_SOURCES, results)}
    if not any(news.values()):
        raise ConnectionError("Couldn't reach any news source.")
    return news


def newest_first(news):
    """Flatten {source: [articles]} into one list, newest first, without duplicate headlines."""
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)   # some feeds keep years-old evergreen posts
    seen, merged = set(), []
    for art in sorted((a for arts in news.values() for a in arts),
                      key=lambda a: a["date"] or oldest, reverse=True):
        key = art["title"].lower()
        if art["date"] and art["date"] < cutoff:
            continue
        if key not in seen:
            seen.add(key)
            merged.append(art)
    return merged


# The names newsrooms actually use, when they differ from the official company name
BRAND_ALIASES = {
    "SPCX": ["SpaceX"], "GOOGL": ["Google", "Alphabet"], "GOOG": ["Google", "Alphabet"], "META": ["Meta", "Facebook"],
    "BRK-B": ["Berkshire Hathaway", "Berkshire"], "BRK-A": ["Berkshire Hathaway", "Berkshire"], "KO": ["Coca-Cola"],
    "JPM": ["JPMorgan"], "XOM": ["Exxon"], "LLY": ["Eli Lilly", "Lilly"], "UNH": ["UnitedHealth"], "TSM": ["TSMC"],
    "BABA": ["Alibaba"], "WMT": ["Walmart"], "COST": ["Costco"], "MA": ["Mastercard"], "V": ["Visa"],
    "PG": ["Procter & Gamble", "P&G"], "JNJ": ["Johnson & Johnson", "J&J"], "HD": ["Home Depot"],
    "DIS": ["Disney"], "MCD": ["McDonald's"], "NKE": ["Nike"], "SBUX": ["Starbucks"], "F": ["Ford"],
    "GM": ["General Motors"], "BA": ["Boeing"], "INTC": ["Intel"], "AMD": ["AMD"], "CRM": ["Salesforce"],
    "ORCL": ["Oracle"], "AVGO": ["Broadcom"], "NFLX": ["Netflix"], "PLTR": ["Palantir"], "UBER": ["Uber"],
    "ABNB": ["Airbnb"], "PYPL": ["PayPal"], "NVDA": ["Nvidia"], "TSLA": ["Tesla"], "AMZN": ["Amazon"],
    "AAPL": ["Apple"], "MSFT": ["Microsoft"], "BAC": ["Bank of America"], "WFC": ["Wells Fargo"],
    "GS": ["Goldman Sachs"], "MS": ["Morgan Stanley"], "C": ["Citigroup", "Citi"], "T": ["AT&T"],
    "VZ": ["Verizon"], "PEP": ["PepsiCo", "Pepsi"], "CVX": ["Chevron"], "PFE": ["Pfizer"], "MRK": ["Merck"],
    "ABBV": ["AbbVie"], "BTC-USD": ["Bitcoin"], "ETH-USD": ["Ethereum", "Ether"], "SOL-USD": ["Solana"],
    "SPY": ["S&P 500"], "VOO": ["S&P 500"], "QQQ": ["Nasdaq 100", "Nasdaq"], "^GSPC": ["S&P 500"],
    "^DJI": ["Dow Jones", "Dow"], "^IXIC": ["Nasdaq"], "^RUT": ["Russell 2000"], "GC=F": ["gold"],
    "CL=F": ["oil", "crude"], "COIN": ["Coinbase"], "HOOD": ["Robinhood"], "RIVN": ["Rivian"], "ARM": ["Arm"],
}
GENERIC_WORDS = {"the", "first", "american", "america", "united", "general", "international", "global",
                 "national", "new", "space", "technologies", "technology", "group", "holdings", "financial",
                 "energy", "bank", "capital", "trust", "fund", "company", "corporation", "industries", "systems",
                 "solutions", "services", "communications", "pharmaceuticals", "therapeutics", "health", "media",
                 "entertainment", "resources", "partners", "royal", "china", "north", "south", "west", "east",
                 "digital", "data", "software", "motors", "airlines", "foods", "spdr", "ishares", "vanguard",
                 "invesco", "select", "sector", "index", "advanced", "applied", "western", "eastern", "pacific",
                 "atlantic", "southern", "northern", "consolidated", "universal", "standard", "allied"}


def _clean_company(name):
    cleaned = re.sub(r"[,.]|\b(Inc|Incorporated|Corporation|Corp|Company|Co|Ltd|Limited|plc|PLC|Holdings|"
                     r"Group|N\.?V|S\.?A|AG|SE|Class [A-C]|The|New|USD|ETF|Trust)\b", " ", name or "")
    return re.sub(r"\s+", " ", cleaned).strip()


def company_names(symbol, info):
    """Names a company goes by in headlines: known brand names, its cleaned official names and,
    when distinctive, the first word (e.g. "Nvidia" from "NVIDIA Corporation")."""
    names = list(BRAND_ALIASES.get(symbol, []))
    for raw in (info.get("shortName"), info.get("longName")):
        cleaned = _clean_company(tidy_name(raw))
        if len(cleaned) >= 3:
            names.append(cleaned)
            first = cleaned.split()[0]
            if len(first) >= 4 and first.lower() not in GENERIC_WORDS:
                names.append(first)
    seen, out = set(), []
    for n in names:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out


def company_matcher(symbol, names):
    """Function that tells whether a piece of text is about the company (by name or ticker)."""
    words = re.compile(r"(?<![\w$])(" + "|".join(re.escape(n) for n in names) + r")(?![\w])", re.I) if names else None
    plain = symbol.lstrip("^").split("-")[0].split("=")[0]
    ticker = re.compile(r"(?<![\w])\$?" + re.escape(plain) + r"(?![\w])") if len(plain) >= 3 else None
    return lambda text: bool((words and words.search(text)) or (ticker and ticker.search(text)))


def _domain(url):
    return urlparse(url).netloc.lower().replace("www.", "")


def fetch_web_news(query, count=30):
    """News search across the whole web (Bing News), with links straight to each publisher.
    Yahoo and MSN copies are dropped so every link goes to the original site."""
    def fetch():
        url = "https://www.bing.com/news/search?" + urlencode({"q": query, "format": "rss", "count": count})
        text = http_get(url, timeout=10).decode("utf-8", "ignore")
        text = re.sub(r'\sxmlns:News="[^"]*"', ' xmlns:News="urn:bing-news"', text)
        text = re.sub(r"&(?!(amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", text)
        articles = []
        for item in ET.fromstring(text).iter("item"):
            link = item.findtext("link") or ""
            link = parse_qs(urlparse(link).query).get("url", [link])[0]
            domain = _domain(link)
            if not link or domain.endswith(("yahoo.com", "msn.com", "bing.com")):
                continue
            outlet = next((sid for d, sid in SOURCE_DOMAINS.items() if domain == d or domain.endswith("." + d)), None)
            source_name = re.sub(r"\s+on MSN$", "", item.findtext("{urn:bing-news}Source") or domain)
            articles.append({"source": outlet or "web", "source_name": source_name, "rank": 0, "link": link,
                             "title": _clean(item.findtext("title")), "summary": _clean(item.findtext("description")),
                             "date": _parse_date(item.findtext("pubDate")), "image": None})
        return articles
    return _cached(("web-news", query.lower()), 10 * 60, fetch) or []


ACCESS_FILE = os.path.join(DATA_DIR, "article_access.json")
_ACCESS = None
_ACCESS_LOCK = threading.Lock()
_ACCESS_CHECKED = set()
ACCESS_PAGE_HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                                     "Chrome/130.0 Safari/537.36", "Accept-Language": "en-US,en;q=0.9"}


def _access_cache():
    global _ACCESS
    if _ACCESS is None:
        try:
            with open(ACCESS_FILE, "r", encoding="utf-8") as f:
                _ACCESS = json.load(f)
        except (OSError, ValueError):
            _ACCESS = {}
    return _ACCESS


def article_access(article):
    """free / limited / paywall, or None when unknown. Per-article results win over outlet policy."""
    link = article["link"]
    checked = _access_cache().get(link)
    if checked in ("free", "limited", "paywall"):
        return checked
    if "cnbc.com" in link and "/pro/" in link:
        return "paywall"                      # CNBC PRO stories need a subscription
    src = SOURCES_BY_ID.get(article["source"])
    if src:
        return src["access"]
    domain = _domain(link)
    return next((acc for d, acc in DOMAIN_ACCESS.items() if domain == d or domain.endswith("." + d)), None)


def needs_access_check(article):
    link = article["link"]
    if link in _ACCESS_CHECKED or link in _access_cache():
        return False
    src = SOURCES_BY_ID.get(article["source"])
    if src:   # big paywalled sites block automated checks, so only metered outlets are worth checking
        return src["access"] == "limited"
    return article_access(article) is None


def check_article_access(articles):
    """Open each article page and read the paywall marker publishers add for search engines
    ("isAccessibleForFree" or "article:content_tier"). Results are saved on disk."""
    def one(article):
        link = article["link"]
        _ACCESS_CHECKED.add(link)
        try:
            req = request.Request(link, headers=ACCESS_PAGE_HEADERS)
            with request.urlopen(req, timeout=8) as resp:
                page = resp.read(600_000).decode("utf-8", "ignore")
        except Exception:
            return link, None
        flag = re.search(r'"isAccessibleForFree"\s*:\s*"?(true|false)', page, re.I)
        tier = re.search(r'article:content_tier"\s+content="(\w+)"|content="(\w+)"\s+(?:name|property)="article:content_tier',
                         page, re.I)
        src = SOURCES_BY_ID.get(article["source"])
        if flag:
            if flag.group(1).lower() == "true":
                return link, "free"
            return link, src["access"] if src else "paywall"    # metered sites mark everything "not free"
        if tier:
            value = (tier.group(1) or tier.group(2)).lower()
            return link, {"free": "free", "metered": "limited", "locked": "paywall"}.get(value)
        # Paywalled pages must carry one of the markers above for Google, so a page that opened normally
        # without one is free to read. (Followed outlets keep their known policy.)
        return link, None if src else "free"

    with ThreadPoolExecutor(max_workers=6) as pool:
        results = dict(pool.map(one, articles))
    found = {k: v for k, v in results.items() if v}
    if found:
        with _ACCESS_LOCK:
            cache = _access_cache()
            cache.update(found)
            if len(cache) > 4000:            # keep the file small
                for key in list(cache)[:len(cache) - 4000]:
                    del cache[key]
            try:
                with open(ACCESS_FILE, "w", encoding="utf-8") as f:
                    json.dump(cache, f)
            except OSError:
                pass
    return results


def fetch_stock_news(symbol, info, pool_news, limit=10):
    """Finance headlines about one company: the followed outlets first, then a web news search so
    stories aren't missed just because they've scrolled out of the outlets' latest feeds."""
    names = company_names(symbol, info)
    matches = company_matcher(symbol, names)
    kind = info.get("quoteType")
    brand = names[0] if names else symbol
    if kind == "CRYPTOCURRENCY":
        queries = [f"{brand} price"]
    elif symbol.startswith("^") or "=" in symbol:
        queries = [brand]
    else:
        queries = [f"{brand} stock"]
        plain = symbol.split("-")[0]
        if len(plain) >= 3 and plain.lower() != brand.lower():
            queries.append(f"{plain} stock")
    with ThreadPoolExecutor(max_workers=len(queries)) as pool:
        web = [a for batch in pool.map(lambda q: _safe(fetch_web_news, q), queries) for a in batch]
    cutoff = datetime.now(timezone.utc) - timedelta(days=45)
    oldest = datetime.min.replace(tzinfo=timezone.utc)
    found, seen = [], set()
    for art in newest_first(pool_news) + sorted(web, key=lambda a: a["date"] or oldest, reverse=True):
        text = art["title"] + " " + art["summary"]
        key = re.sub(r"[^a-z0-9]", "", art["title"].lower())[:60]
        if key in seen or not matches(text) or not FINANCE_PATTERN.search(text):
            continue
        if art["date"] and art["date"] < cutoff:
            continue
        seen.add(key)
        found.append(art)
    found.sort(key=lambda a: a["date"] or oldest, reverse=True)
    return {"articles": found[:limit], "names": names}


# --- Going easy on Yahoo Finance -------------------------------------------------------------
# Yahoo slows down or blocks a network that asks too often, and a classroom on one Wi-Fi connection
# looks like a single very busy computer. So prices refresh at a chosen pace, pages share what was
# already downloaded, and the app holds back for a few minutes when Yahoo answers "Too Many Requests".
REFRESH_PACES = {"live": 1, "balanced": 5, "light": 15}     # minutes between automatic price refreshes
DEFAULT_PACE = "balanced"
CLOSED_MARKET_MINUTES = 15      # prices barely move while the stock market is closed
QUOTE_TTL = 55                  # seconds a downloaded price is shared between pages
_BACKOFF = {"until": 0.0, "strikes": 0, "last": 0.0}


def rate_limited():
    """Seconds left before the app asks Yahoo Finance again by itself (0 when it isn't holding back)."""
    return max(0.0, _BACKOFF["until"] - time.time())


def note_rate_limit(problem):
    """Look at an error or a log line. If it is Yahoo saying "too many requests", hold back for a while:
    about 3 minutes the first time, doubling when it keeps happening, 15 at most. The wait is stretched
    by a random amount so a room full of apps doesn't come back at the same instant."""
    text = f"{type(problem).__name__} {problem}"
    if "Too Many Requests" not in text and "RateLimit" not in text and "Rate limited" not in text:
        return False
    now = time.time()
    if now >= _BACKOFF["until"]:
        _BACKOFF["strikes"] = _BACKOFF["strikes"] + 1 if now - _BACKOFF["last"] < 45 * 60 else 1
        _BACKOFF["last"] = now
        _BACKOFF["until"] = now + min(15, 3 * 2 ** (_BACKOFF["strikes"] - 1)) * 60 * random.uniform(1.0, 1.4)
    return True


def rate_limit_text():
    resume = datetime.now() + timedelta(seconds=rate_limited())
    return ("Yahoo Finance is limiting how often this network can ask for prices. "
            f"Trying again around {clock_time(resume)}.")


def explain(error, fallback):
    """What to tell the person when a download failed: the real reason if Yahoo is rate-limiting."""
    note_rate_limit(error)
    return rate_limit_text() if rate_limited() else fallback


def refresh_words(settings):
    minutes = REFRESH_PACES.get(settings.get("refresh"), REFRESH_PACES[DEFAULT_PACE])
    return "every minute" if minutes == 1 else f"every {minutes} minutes"


class YahooBusy(Exception):
    """Raised instead of an empty answer when Yahoo Finance is rate-limiting this network."""

    def __init__(self):
        super().__init__(rate_limit_text())


class _YahooLogWatch(logging.Handler):
    """yfinance reports some failed downloads only in its log; this spots "Too Many Requests" there."""

    def emit(self, record):
        try:
            note_rate_limit(record.getMessage())
        except Exception:
            pass


logging.getLogger("yfinance").addHandler(_YahooLogWatch())


def fetch_quotes(symbols):
    """Last price, day change and a 1-month sparkline for each symbol.

    Prices downloaded in the last minute are reused, so Home, Markets, Watchlist, Portfolio and price
    alerts don't each ask Yahoo for the same thing. While Yahoo is rate-limiting, known prices are served
    as they are and only symbols never seen before are requested.
    """
    if not symbols:
        return {}
    now, holding = time.time(), rate_limited()
    quotes, need = {}, []
    with _CACHE_LOCK:
        for sym in symbols:
            hit = _CACHE.get(("quote", sym))
            if hit and (holding or now - hit[0] < QUOTE_TTL):
                quotes[sym] = hit[1]
            elif sym not in need:
                need.append(sym)
    if not need:
        return quotes
    with YF_LOCK:
        df = yf.download(need, period="1mo", interval="1d", group_by="ticker",
                         auto_adjust=True, progress=False, threads=True)
    fresh = {}
    for sym in need:
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
        fresh[sym] = {
            "last": last, "prev": prev, "change": last - prev,
            "pct": (last / prev - 1) * 100 if prev else 0.0,
            "high": float(sub["High"].iloc[-1]), "low": float(sub["Low"].iloc[-1]),
            "volume": float(sub["Volume"].iloc[-1]),
            "spark": [float(v) for v in close.tail(22)],
        }
    with _CACHE_LOCK:
        for sym, item in fresh.items():
            _CACHE[("quote", sym)] = (time.time(), item)
    quotes.update(fresh)
    if not quotes and rate_limited():
        raise YahooBusy()
    return quotes


def forget_quotes():
    """F5: drop the shared prices so the next load asks Yahoo again (not while it is rate-limiting)."""
    if rate_limited():
        return
    with _CACHE_LOCK:
        for key in [k for k in _CACHE if k[0] == "quote"]:
            del _CACHE[key]


# --- Is there a newer version? -----------------------------------------------------------------
def version_numbers(text):
    """"v12", "12.0" and "12.0.0" all mean (12, 0, 0)."""
    numbers = [int(n) for n in re.findall(r"\d+", str(text))[:3]]
    return tuple(numbers + [0] * (3 - len(numbers)))


def latest_release():
    """The newest published version, e.g. "12", or None if it can't be told.

    Read from where GitHub's "latest release" link redirects to. That needs no account, sends nothing
    about this computer or the person using it, and isn't subject to GitHub's API limits.
    """
    req = request.Request(RELEASES_URL + "/latest", headers=HTTP_HEADERS, method="HEAD")
    with request.urlopen(req, timeout=10) as resp:
        found = re.search(r"/releases/tag/v?(\d+(?:\.\d+)*)", resp.geturl())
    return found.group(1) if found else None


def fetch_index_history(range_key):
    """Closing levels of the four major indices over a range, aligned on one time axis."""
    period, interval = OVERVIEW_RANGES[range_key]
    with YF_LOCK:
        df = yf.download([s for _, s in INDEXES], period=period, interval=interval,
                         auto_adjust=True, progress=False, threads=True)
    close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
    return close.dropna(how="all").ffill().bfill()


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


_CACHE = {}                  # (kind, key...) -> (time fetched, value)
_CACHE_LOCK = threading.Lock()


def _cached(key, max_age, fetch):
    """Return a recent cached value, or fetch and remember it. Empty results aren't cached."""
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
    if hit and (time.time() - hit[0] < max_age or rate_limited()):     # while rate-limited, keep what we have
        return hit[1]
    value = fetch()
    if value is not None and not getattr(value, "empty", False) and not (isinstance(value, dict) and not value):
        with _CACHE_LOCK:
            _CACHE[key] = (time.time(), value)
    return value


def forget_symbol(symbol):
    """Drop cached prices and details for a symbol so the next load is fresh."""
    with _CACHE_LOCK:
        for key in [k for k in _CACHE if len(k) > 1 and k[1] == symbol]:
            del _CACHE[key]


def _download_history(symbol, period, interval):
    def fetch():
        try:
            hist = yf.Ticker(symbol).history(period=period, interval=interval, auto_adjust=True)
        except Exception as exc:
            note_rate_limit(exc)
            return pd.DataFrame()
        if hist.empty:
            return hist
        hist = hist[["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Close"])
        if interval == "1d":
            hist["MA50"] = hist["Close"].rolling(50).mean()
            hist["MA200"] = hist["Close"].rolling(200).mean()
        return hist
    return _cached(("history", symbol, period, interval), 15 * 60 if interval == "1d" else 60, fetch)


def fetch_history(symbol, range_key):
    fetch_period, interval, span = RANGES[range_key]
    hist = _download_history(symbol, fetch_period, interval)
    if hist.empty or interval != "1d":
        return hist
    last = hist.index[-1]
    if span == "ytd":
        hist = hist[hist.index >= last.replace(month=1, day=1, hour=0, minute=0, second=0)]
    elif span:
        hist = hist[hist.index >= last - pd.Timedelta(days=span)]
    if len(hist) > 1600:   # decades of daily bars: one bar per week looks the same and draws far faster
        hist = hist.resample("W-FRI").agg({"Open": "first", "High": "max", "Low": "min", "Close": "last",
                                           "Volume": "sum", "MA50": "last", "MA200": "last"})
        hist = hist.dropna(subset=["Close"])
    return hist


_INFO_SLOTS = threading.Semaphore(4)   # too many lookups at once makes Yahoo reject the session ("Invalid Crumb")


def fetch_info(symbol):
    """Company details, cached for 5 minutes. Incomplete answers are retried and never cached."""
    with _CACHE_LOCK:
        hit = _CACHE.get(("info", symbol))
    if hit and (time.time() - hit[0] < 5 * 60 or rate_limited()):
        return hit[1]
    info, complete = _fetch_info(symbol)
    if complete:
        with _CACHE_LOCK:
            _CACHE[("info", symbol)] = (time.time(), info)
    return info


def _fetch_info(symbol):
    t = yf.Ticker(symbol)
    info, complete = {}, False
    for attempt in range(3):
        try:
            with _INFO_SLOTS:
                info = dict(t.info or {})
            # after a rejected session yfinance quietly returns a cut-down record (no sector, no margins)
            complete = bool(info.get("quoteType")) and (info.get("quoteType") != "EQUITY" or
                                                        "sector" in info or "profitMargins" in info)
            if complete:
                break
        except Exception:
            pass
        time.sleep(0.5 * (attempt + 1))
    if is_missing(info.get("regularMarketPrice")) or is_missing(info.get("regularMarketPreviousClose")):
        try:
            fast = t.fast_info
            info.setdefault("regularMarketPrice", fast.last_price)
            info.setdefault("regularMarketPreviousClose", fast.previous_close)
        except Exception:
            pass
    return info, complete


def load_symbol(query, range_key):
    """Everything the Markets page needs for one symbol. Prices and company details download
    at the same time; names like 'costco' go straight to a search instead of a failed lookup."""
    text = query.strip()
    symbol = text.upper()
    looks_like_name = " " in text or (text.isalpha() and len(text) > 5) or not TICKER_RE.match(symbol)
    if looks_like_name:
        symbol, _ = search_symbol(text)
    with ThreadPoolExecutor(max_workers=2) as pool:
        info = pool.submit(fetch_info, symbol)
        hist = fetch_history(symbol, range_key)
        if hist.empty and not looks_like_name:
            symbol, _ = search_symbol(text)
            info = pool.submit(fetch_info, symbol)
            hist = fetch_history(symbol, range_key)
        if hist.empty:
            raise LookupError(f"No price data found for “{query}”.")
        return {"symbol": symbol, "hist": hist, "info": info.result()}


def _report_timing(when):
    """'before the open', 'after the close' or 'during market hours' from a report timestamp (ET)."""
    when = when.tz_convert(EASTERN) if EASTERN and when.tzinfo else when
    minutes = when.hour * 60 + when.minute
    if minutes in (0, 15 * 60):          # Yahoo's placeholder when the company hasn't confirmed a time
        return "time not confirmed yet"
    if minutes < 9 * 60 + 30:
        return "before the market opens"
    if minutes >= 16 * 60:
        return "after the market closes"
    return "during market hours"


def fetch_earnings(symbol):
    """The last reported quarter (EPS vs estimate, revenue vs a year ago), the beat/miss record for
    recent quarters, and the next report date with its estimate. Cached for 6 hours."""
    def fetch():
        t = yf.Ticker(symbol)
        with _INFO_SLOTS:
            dates = t.get_earnings_dates(limit=12)
        if dates is None or dates.empty:
            return None
        dates = dates.sort_index()
        now = pd.Timestamp.now(tz=dates.index.tz)
        reported = dates[dates["Reported EPS"].notna() & (dates.index <= now)]
        upcoming = dates[(dates.index > now - pd.Timedelta(hours=12)) & dates["Reported EPS"].isna()]
        result = {"last": None, "next": None, "record": []}
        if not reported.empty:
            when = reported.index[-1]
            row = reported.iloc[-1]
            last = {"date": when.to_pydatetime(), "timing": _report_timing(when),
                    "eps": float(row["Reported EPS"]),
                    "estimate": None if pd.isna(row["EPS Estimate"]) else float(row["EPS Estimate"]),
                    "surprise": None if pd.isna(row["Surprise(%)"]) else float(row["Surprise(%)"]),
                    "revenue": None, "revenue_growth": None, "quarter": None,
                    "net_income": None, "net_income_prev": None, "reaction": None}
            try:   # revenue for the quarter that was reported, and the same quarter a year earlier
                with _INFO_SLOTS:
                    stmt = t.quarterly_income_stmt
                if stmt is not None and "Total Revenue" in stmt.index:
                    revenue = stmt.loc["Total Revenue"].dropna().sort_index()
                    report_day = when.tz_localize(None) if when.tzinfo else when
                    # companies report a few weeks after the quarter ends; older columns mean the new
                    # quarter isn't in the statements yet, so don't show last quarter's revenue instead
                    ends = [d for d in revenue.index if pd.Timedelta(0) < report_day - d <= pd.Timedelta(days=80)]
                    if ends:
                        end = max(ends)
                        last["revenue"] = float(revenue[end])
                        last["quarter"] = end.to_pydatetime()
                        year_ago = [d for d in revenue.index if abs((end - d).days - 365) <= 20]
                        if year_ago and revenue[year_ago[0]]:
                            last["revenue_growth"] = (last["revenue"] / float(revenue[year_ago[0]]) - 1) * 100
                        if "Net Income" in stmt.index:
                            profit = stmt.loc["Net Income"]
                            if not pd.isna(profit.get(end)):
                                last["net_income"] = float(profit[end])
                            if year_ago and not pd.isna(profit.get(year_ago[0])):
                                last["net_income_prev"] = float(profit[year_ago[0]])
            except Exception:
                pass
            last["reaction"] = _earnings_reaction(symbol, when, last["timing"])
            result["last"] = last
            for when, row in reported.iloc[-4:].iterrows():
                surprise = row["Surprise(%)"]
                if not pd.isna(surprise):
                    result["record"].append((when.to_pydatetime(), float(surprise)))
        if not upcoming.empty:
            when = upcoming.index[0]
            estimate = upcoming.iloc[0]["EPS Estimate"]
            timing = _report_timing(when)
            result["next"] = {"date": when.to_pydatetime(), "timing": timing,
                              "time": "" if "confirmed" in timing else
                              clock_time(when.tz_convert(EASTERN) if EASTERN else when) + " ET",
                              "estimate": None if pd.isna(estimate) else float(estimate)}
        return result
    return _cached(("earnings", symbol), 6 * 3600, fetch)


def _earnings_reaction(symbol, when, timing):
    """How the stock moved on the first trading day after the report: (percent, label) or None."""
    try:
        hist = _download_history(symbol, "10y", "1d")
        if hist.empty:
            return None
        close = hist["Close"]
        days = [d.date() for d in close.index]
        report = (when.tz_convert(EASTERN) if EASTERN and when.tzinfo else when).date()
        if timing == "after the market closes":     # reaction shows up the next morning
            before = [i for i, d in enumerate(days) if d <= report]
            after = [i for i, d in enumerate(days) if d > report]
            label_text = "the next trading day"
        else:                                         # reported before or during the session
            before = [i for i, d in enumerate(days) if d < report]
            after = [i for i, d in enumerate(days) if d >= report]
            label_text = "on the day of the report"
        if not before or not after:
            return None
        return (float(close.iloc[after[0]]) / float(close.iloc[before[-1]]) - 1) * 100, label_text
    except Exception:
        return None


def earnings_summary(company, last):
    """A short plain-English summary of the last earnings report, written from the numbers."""
    word, _ = beat_word(last["surprise"])
    verb = {"Beat": "beat expectations", "Missed": "fell short of expectations",
            "In line": "came in line with expectations"}.get(word, "reported results")
    quarter = last.get("quarter")
    period = ("for the quarter ended " + quarter.strftime("%B %d").replace(" 0", " ")) if quarter else "for its latest quarter"

    def per_share(v):
        return f"${v:.2f} a share" if v >= 0 else f"a loss of ${abs(v):.2f} a share"

    eps, est = last["eps"], last["estimate"]
    if est is not None:
        compare = {"Beat": "topping", "Missed": "short of"}.get(word, "matching")
        expected = f"${est:.2f}" if est >= 0 else f"a ${abs(est):.2f} loss"
        eps_part = f"{'earnings of ' if eps >= 0 else ''}{per_share(eps)}, {compare} the {expected} analysts expected"
    else:
        eps_part = f"{'earnings of ' if eps >= 0 else ''}{per_share(eps)}"
    first = f"{company} {verb} {period}, with {eps_part}"
    revenue, growth = last.get("revenue"), last.get("revenue_growth")
    if revenue and growth is not None:
        first += f". Revenue {'rose' if growth >= 0 else 'fell'} {abs(growth):.1f}% from a year earlier to ${fmt_big(revenue)}"
    elif revenue:
        first += f", on revenue of ${fmt_big(revenue)}"
    sentences = [first + "."]

    profit, before = last.get("net_income"), last.get("net_income_prev")
    if profit is not None:
        if profit >= 0:
            text = f"Profit was ${fmt_big(profit)}"
            if before and before > 0:
                change = (profit / before - 1) * 100
                text += f", {'up' if change >= 0 else 'down'} {abs(change):.0f}% from a year ago"
            elif before is not None and before < 0:
                text += ", turning around a loss a year ago"
            if revenue:
                text += f" (a {profit / revenue * 100:.0f}% profit margin)"
        else:
            text = f"It posted a net loss of ${fmt_big(-profit)}"
            if before is not None and before < 0:
                text += f", {'narrower' if -profit < -before else 'wider'} than the ${fmt_big(-before)} loss a year ago"
            elif before is not None and before > 0:
                text += ", after a profit a year ago"
        sentences.append(text + ".")

    reaction = last.get("reaction")
    if reaction:
        move, when = reaction
        if abs(move) < 0.1:
            sentences.append(f"The stock was little changed {when}.")
        else:
            sentences.append(f"The stock {'rose' if move > 0 else 'fell'} {abs(move):.1f}% {when}.")
    return " ".join(sentences)


EARNINGS_NEWS = re.compile(r"\b(earnings|results|quarter|quarterly|q[1-4]|revenue|profit|eps|guidance|beat|beats|"
                           r"miss|misses|sales|outlook)\b", re.I)


def beat_word(surprise):
    """(word, rating) for an EPS surprise %: within ±1% counts as in line."""
    if surprise is None:
        return "Reported", None
    if surprise > 1:
        return "Beat", "good"
    if surprise < -1:
        return "Missed", "weak"
    return "In line", "fair"


_PREFETCHED = set()


def prefetch(symbol, range_key="1Y"):
    """Start downloading a symbol in the background (e.g. when the mouse moves over it)."""
    key = (symbol, range_key)
    if key in _PREFETCHED:
        return
    _PREFETCHED.add(key)

    def work():
        try:
            fetch_history(symbol, range_key)
            fetch_info(symbol)
        except Exception:
            pass
        finally:
            threading.Timer(5 * 60, lambda: _PREFETCHED.discard(key)).start()
    threading.Thread(target=work, daemon=True).start()


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
# 5. Portfolio and calendar downloads
# -----------------------------------------------------------------------------
# --- portfolio ---------------------------------------------------------------------
def fetch_portfolio(symbols):
    """Live quotes plus company details (sector, dividend) for every holding."""
    quotes = fetch_quotes(symbols)
    with ThreadPoolExecutor(max_workers=8) as pool:
        infos = dict(zip(symbols, pool.map(fetch_info, symbols)))
    return {"quotes": quotes, "infos": infos}


def fetch_portfolio_history(symbols):
    """Five years of daily closes for the holdings and the S&P 500."""
    def fetch():
        with YF_LOCK:
            df = yf.download(list(symbols) + ["^GSPC"], period="5y", interval="1d", auto_adjust=True,
                             progress=False, threads=True)
        close = df["Close"] if isinstance(df.columns, pd.MultiIndex) else df[["Close"]]
        return close.ffill()
    return _cached(("portfolio-history", tuple(sorted(symbols))), 15 * 60, fetch)


# --- calendar ------------------------------------------------------------------------
FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BEA_URL = "https://www.bea.gov/news/schedule"
CENSUS_URL = "https://www.census.gov/economic-indicators/calendar-listview.html"
BLS_URL = "https://www.bls.gov/schedule/news_release/{}.htm"
BLS_HEADERS = {"User-Agent": "InsightByMilton/7.0 (+https://www.themiltonreview.net)"}   # BLS asks apps to identify themselves


def _table_rows(page):
    return [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", row))).strip()
            for row in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S)]


def _parse_day(text, *formats):
    text = text.replace("Sept", "Sep").replace(".", "").strip()
    for fmt in formats or ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def fetch_fed_meetings():
    page = http_get(FED_URL).decode("utf-8", "ignore")
    parts = re.split(r"(\d{4}) FOMC Meetings", page)
    events = []
    for i in range(1, len(parts), 2):
        year = parts[i]
        for month, days in re.findall(r"fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>.*?"
                                      r"fomc-meeting__date[^>]*>([^<]+)<", parts[i + 1], re.S):
            if not re.match(r"^\d", days.strip()) or "notation" in days or "unscheduled" in days.lower():
                continue
            projections = "*" in days
            days = days.replace("*", "").strip()
            date = _parse_day(f"{month.split('/')[-1]} {days.split('-')[-1]}, {year}", "%B %d, %Y", "%b %d, %Y")
            if date:
                events.append({"type": "fed", "date": date, "time": "2:00 PM ET",
                               "title": "Fed interest-rate decision",
                               "detail": f"FOMC meeting {month} {days}"
                                         + (" · with new economic projections" if projections else "")})
    return events


def fetch_bls(series):
    names = {"cpi": ("Consumer Price Index (CPI)", "Inflation for {}"),
             "empsit": ("Jobs report (Employment Situation)", "Hiring and unemployment for {}")}
    title, detail = names[series]
    req = request.Request(BLS_URL.format(series), headers=BLS_HEADERS)
    with request.urlopen(req, timeout=15) as resp:
        page = resp.read().decode("utf-8", "ignore")
    events = []
    for row in _table_rows(page):
        m = re.match(r"^([A-Z][a-z]+ \d{4}) ([A-Z][a-z]{2,4}\.? \d{1,2}, \d{4}) (\d{1,2}:\d{2} [AP]M)", row)
        if m:
            date = _parse_day(m.group(2))
            if date:
                events.append({"type": "economy", "date": date, "time": m.group(3).lstrip("0") + " ET",
                               "title": title, "detail": detail.format(m.group(1))})
    return events


def fetch_bea():
    page = http_get(BEA_URL).decode("utf-8", "ignore")
    events, year, last_month = [], datetime.now().year, 0
    for row in _table_rows(page):
        heading = re.match(r"^Year (\d{4})", row)
        if heading:
            year, last_month = int(heading.group(1)), 0
            continue
        m = re.match(r"^([A-Z][a-z]+ \d{1,2}) (\d{1,2}:\d{2} [AP]M) (?:N ?ews )?(.+)$", row)
        if not m or not (m.group(3).startswith("GDP (") or m.group(3).startswith("Personal Income and Outlays")):
            continue
        date = _parse_day(f"{m.group(1)}, {year}", "%B %d, %Y")
        if date is None:
            continue
        if date.month < last_month:     # schedule rolled into the next year
            year += 1
            date = date.replace(year=year)
        last_month = date.month
        is_gdp = m.group(3).startswith("GDP")
        events.append({"type": "economy", "date": date, "time": m.group(2) + " ET",
                       "title": "GDP (economic growth)" if is_gdp else "PCE inflation & consumer spending",
                       "detail": m.group(3)})
    return events


def fetch_retail_sales():
    page = http_get(CENSUS_URL).decode("utf-8", "ignore")
    events = []
    for row in _table_rows(page):
        m = re.match(r"^Advance Monthly Sales for Retail and Food Services ([A-Z][a-z]+ \d{1,2}, \d{4}) "
                     r"(\d{1,2}:\d{2} [AP]M) ([A-Z][a-z]+ \d{4})", row)
        if m:
            date = _parse_day(m.group(1), "%B %d, %Y")
            if date:
                events.append({"type": "economy", "date": date, "time": m.group(2) + " ET",
                               "title": "Retail sales", "detail": f"Consumer spending at stores for {m.group(3)}"})
    return events


def fetch_company_events(symbol):
    cal = _cached(("calendar", symbol), 6 * 3600, lambda: dict(yf.Ticker(symbol).calendar or {})) or {}
    info = fetch_info(symbol)
    name = tidy_name(info.get("shortName")) or symbol

    def as_datetime(d):
        return datetime(d.year, d.month, d.day) if d else None

    events = []
    dates = cal.get("Earnings Date") or []
    if dates:
        parts = []
        if not is_missing(cal.get("Earnings Average")):
            parts.append(f"EPS estimate ${cal['Earnings Average']:.2f}")
        if not is_missing(cal.get("Revenue Average")):
            parts.append(f"revenue estimate ${fmt_big(cal['Revenue Average'])}")
        events.append({"type": "earnings", "date": as_datetime(dates[0]), "symbol": symbol, "time": "",
                       "title": f"{name} earnings", "detail": " · ".join(parts) or "Quarterly results"})
    amount = info.get("lastDividendValue")
    per_share = f" · last dividend ${amount:.2f} per share" if amount else ""
    if cal.get("Ex-Dividend Date"):
        events.append({"type": "dividend", "date": as_datetime(cal["Ex-Dividend Date"]), "symbol": symbol,
                       "time": "", "title": f"{name} ex-dividend date",
                       "detail": "Own the shares before this day to receive the next dividend" + per_share})
    if cal.get("Dividend Date"):
        events.append({"type": "dividend", "date": as_datetime(cal["Dividend Date"]), "symbol": symbol,
                       "time": "", "title": f"{name} dividend paid", "detail": "Payment date" + per_share})
    return events


ECONOMIC_SOURCES = [("Federal Reserve", fetch_fed_meetings), ("BLS (CPI)", lambda: fetch_bls("cpi")),
                    ("BLS (jobs)", lambda: fetch_bls("empsit")), ("BEA", fetch_bea),
                    ("Census Bureau", fetch_retail_sales)]


def fetch_calendar(symbols, days=120):
    """Upcoming events for the next few months, plus the names of any sources that failed."""
    def economic():
        found, failed = [], []
        for name, fn in ECONOMIC_SOURCES:
            try:
                found += fn()
            except Exception:
                failed.append(name)
        return found, failed

    with ThreadPoolExecutor(max_workers=8) as pool:
        econ = pool.submit(lambda: _cached(("economic-calendar",), 6 * 3600, lambda: economic()))
        companies = list(pool.map(lambda sym: _safe(fetch_company_events, sym), symbols))
    econ_events, failed = econ.result()
    today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    order = {"fed": 0, "economy": 1, "earnings": 2, "dividend": 3}
    events = [e for e in econ_events + [e for group in companies for e in group]
              if e["date"] and today <= e["date"] <= today + timedelta(days=days)]
    events.sort(key=lambda e: (e["date"], order[e["type"]], e["title"]))
    return {"events": events, "failed": failed}


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return []


# -----------------------------------------------------------------------------
# 6. Extras for the web server (the Windows app doesn't use these)
# -----------------------------------------------------------------------------
def search_symbols(query, limit=6):
    """Every match for a company name or ticker, best first."""
    found = []
    for item in yf.Search(query, max_results=limit, news_count=0).quotes or []:
        if item.get("symbol"):
            found.append({"symbol": item["symbol"],
                          "name": item.get("shortname") or item.get("longname") or "",
                          "type": item.get("typeDisp") or item.get("quoteType") or "",
                          "exchange": item.get("exchDisp") or item.get("exchange") or ""})
    return found


def trim_cache(max_entries, max_cells=None):
    """Forget the oldest downloads once more than max_entries are held, or once the price tables
    among them add up to more than max_cells numbers. One person's app never collects that many;
    a server that anyone can ask about any ticker would grow without end. Returns how many went."""
    with _CACHE_LOCK:
        kept = cells = dropped = 0
        for key in sorted(_CACHE, key=lambda k: _CACHE[k][0], reverse=True):      # newest first
            size = getattr(_CACHE[key][1], "size", 0)                           # rows x columns of a table
            if kept >= max_entries or (max_cells is not None and size and cells + size > max_cells):
                del _CACHE[key]
                dropped += 1
            else:
                kept, cells = kept + 1, cells + size
        return dropped
