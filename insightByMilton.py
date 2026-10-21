# =============================================================================
#  Insight by Milton
#  A desktop markets companion for The Milton Review (themiltonreview.net)
#
#  Pages:  Home · Markets · News · Watchlist · Bond Market
#  Data:   Yahoo Finance (yfinance), U.S. Treasury, The Milton Review RSS feed
# =============================================================================

import csv
import html
import importlib
import io
import json
import math
import os
import queue
import random
import re
import sys
import threading
import time
import webbrowser
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib import request
from urllib.parse import quote

import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, filedialog

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

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
THEME = "light"
COLOR_NAMES = ("BG", "SURFACE", "SAND", "BORDER", "INK", "MUTED", "FAINT", "ACCENT", "ACCENT_DARK",
               "ACCENT_SOFT", "UP", "UP_SOFT", "DOWN", "DOWN_SOFT", "FAIR", "FAIR_SOFT")
(BG, SURFACE, SAND, BORDER, INK, MUTED, FAINT, ACCENT, ACCENT_DARK, ACCENT_SOFT,
 UP, UP_SOFT, DOWN, DOWN_SOFT, FAIR, FAIR_SOFT) = (THEMES["light"][name] for name in COLOR_NAMES)
RATING_STYLE = {}         # rating -> (text colour, pill colour, word), filled by apply_theme()


def apply_theme(name):
    """Switch every colour constant. Called before the window's widgets are built."""
    global THEME, _LOGO
    THEME = name if name in THEMES else "light"
    globals().update(THEMES[THEME])
    RATING_STYLE.clear()
    RATING_STYLE.update({"good": (UP, UP_SOFT, "Good"), "fair": (FAIR, FAIR_SOFT, "Fair"),
                         "weak": (DOWN, DOWN_SOFT, "Weak"), None: (FAINT, SAND, "Not rated")})
    if "INDEX_COLORS" in globals():
        INDEX_COLORS[:2] = [INK, ACCENT]
    _LOGO = None


def windows_prefers_dark():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except Exception:
        return False


def set_dark_titlebar(window, dark):
    """Ask Windows 10/11 to draw a dark title bar to match dark mode."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


VERSION = "8.0"
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


def bias_text_color(rating):
    """The scale colours are soft; darken them a little when used for text."""
    return blend(BIAS_COLORS[rating], INK, 0.25)

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
SOURCES_BY_ID = {src["id"]: src for src in NEWS_SOURCES}

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
INDEX_COLORS = [INK, ACCENT, "#5B7FA6", "#7E9B6A"]
_LOGO = None
apply_theme("light")
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
    import tkinterdnd2  # noqa: F401


pd = LazyModule("pandas")
yf = LazyModule("yfinance")


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
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
PORTFOLIO_FILE = os.path.join(DATA_DIR, "portfolio.json")
ALERTS_FILE = os.path.join(DATA_DIR, "alerts.json")
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


def fetch_images(urls, max_size=(720, 720)):
    """Download thumbnails in parallel and shrink them here, off the UI thread.
    Failed downloads come back as None."""
    def one(url):
        try:
            if not url:
                return None
            img = fetch_image(url)
            img.thumbnail(max_size, Image.LANCZOS)
            return img
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


def company_pattern(symbol, name):
    """Regex that finds a company in headlines by its short name or ticker."""
    aliases = {"GOOGL": "Google|Alphabet", "GOOG": "Google|Alphabet", "META": "Meta|Facebook",
               "BRK-B": "Berkshire", "BRK-A": "Berkshire"}
    cleaned = re.sub(r"[,.]|\b(Inc|Incorporated|Corporation|Corp|Company|Co|Ltd|Limited|plc|PLC|Holdings|"
                     r"Group|N\.?V|S\.?A|AG|SE|Class [A-C]|The)\b", " ", name or "")
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    names = [re.escape(cleaned)] if len(cleaned) >= 3 else []
    if symbol in aliases:
        names.append(aliases[symbol])
    parts = [r"\b(" + "|".join(names) + r")\b"] if names else []
    words = re.compile("|".join(parts), re.I) if parts else None
    ticker = re.compile(r"\b" + re.escape(symbol) + r"\b") if len(symbol) >= 3 else None
    return lambda text: bool((words and words.search(text)) or (ticker and ticker.search(text)))


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
    if hit and time.time() - hit[0] < max_age:
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
        except Exception:
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
    if hit and time.time() - hit[0] < 5 * 60:
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
# 5. Background worker — runs slow calls off the UI thread
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


# --- portfolio CSV import --------------------------------------------------------------
# Column names seen in broker exports (Fidelity, Schwab, Vanguard, Robinhood, E*TRADE…) and in
# home-made spreadsheets, with spaces and punctuation removed.
CSV_COLUMNS = {
    "symbol": {"symbol", "ticker", "tickersymbol", "symbolcusip", "securitysymbol", "stocksymbol", "instrument",
               "code"},
    "shares": {"quantity", "shares", "qty", "qtyquantity", "sharesquantity", "quantityshares", "units",
               "sharesheld", "numberofshares", "position", "currentquantity", "shareqty", "sharesowned"},
    "cost_each": {"averagecost", "avgcost", "averagecostbasis", "costpershare", "averageprice", "avgprice",
                  "purchaseprice", "pricepaid", "costbasispershare", "averagecostpershare", "unitcost", "buyprice",
                  "averagepurchaseprice", "avgcostpershare", "avgcostshare", "averagecostshare", "costshare", "cost",
                  "averagecostprice", "avgpurchaseprice"},
    "cost_total": {"costbasis", "costbasistotal", "totalcost", "totalcostbasis", "costbasiscb", "bookvalue",
                   "costbasisamount", "totalcostbasisamount"},
    "name": {"description", "name", "securityname", "companyname", "security", "securitydescription",
             "investmentname"},
}
CSV_LABELS = {"symbol": "symbol", "shares": "shares", "cost_each": "average cost per share",
              "cost_total": "total cost (divided by shares)", "name": "name"}
NOT_HOLDINGS = re.compile(r"\b(cash|total|pending|money market|sweep|margin|core position)\b", re.I)


def _csv_key(header):
    return re.sub(r"[^a-z]", "", (header or "").lower())


def _csv_number(text, decimal_comma=False):
    t = (text or "").strip().replace("$", "").replace("%", "").replace("+", "")
    if decimal_comma and "." not in t:
        t = t.replace(",", ".")       # European style: 2,5 means 2.5
    t = t.replace(",", "")
    negative = t.startswith("(") and t.endswith(")")
    t = t.strip("()").strip()
    if t.lower() in ("", "-", "--", "n/a", "na", "none"):
        return None
    try:
        value = float(t)
    except ValueError:
        return None
    return -value if negative else value


def _csv_symbol(raw):
    sym = (raw or "").strip().upper().rstrip("*").strip()
    if re.fullmatch(r"[A-Z]{1,5}[./][A-Z]", sym):     # BRK.B / BRK/B -> BRK-B, as Yahoo writes it
        sym = re.sub(r"[./]", "-", sym)
    return sym


def parse_portfolio_csv(path):
    """Read holdings from a broker export or a simple spreadsheet. Returns the holdings found, the rows
    that were skipped (and why), and which columns were used."""
    raw = open(path, "rb").read()
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    lines = list(csv.reader(text.splitlines(), dialect))
    decimal_comma = dialect.delimiter == ";"

    columns, header_at = None, None
    for i, row in enumerate(lines[:60]):          # broker files often start with a few lines of account info
        found = {}
        for c, cell in enumerate(row):
            key = _csv_key(cell)
            for field, names in CSV_COLUMNS.items():
                if key in names and field not in found:
                    found[field] = c
        if "symbol" in found and "shares" in found:
            columns, header_at = found, i
            break
    if columns is None:
        raise ValueError("Couldn't find the holdings table. The file needs a column for the symbol (e.g. "
                         "“Symbol” or “Ticker”) and one for the number of shares (e.g. “Shares” or “Quantity”).")

    def cell(row, field):
        c = columns.get(field)
        return row[c].strip() if c is not None and c < len(row) else ""

    holdings, skipped = {}, []
    for n, row in enumerate(lines[header_at + 1:], start=header_at + 2):
        if sum(1 for x in row if x.strip()) <= 1:     # blank lines and footnotes/disclaimers
            continue
        raw_symbol, name = cell(row, "symbol"), cell(row, "name")
        sym = _csv_symbol(raw_symbol)
        if not sym:
            skipped.append((n, raw_symbol or (row[0] if row else ""), "no symbol"))
            continue
        if raw_symbol.endswith("**") or NOT_HOLDINGS.search(raw_symbol) or NOT_HOLDINGS.search(name):
            skipped.append((n, raw_symbol, "cash, money market or a total line"))
            continue
        if " " in sym or not TICKER_RE.match(sym) or len(sym) > 10:
            skipped.append((n, raw_symbol, "not a stock or fund symbol (e.g. an option)"))
            continue
        shares = _csv_number(cell(row, "shares"), decimal_comma)
        if not shares or shares <= 0:
            skipped.append((n, raw_symbol, "no share quantity"))
            continue
        cost = _csv_number(cell(row, "cost_each"), decimal_comma)
        if not cost and "cost_total" in columns:
            total = _csv_number(cell(row, "cost_total"), decimal_comma)
            cost = total / shares if total else None
        cost = cost or None       # a cost of 0 almost always means "not filled in"
        h = holdings.get(sym)
        if h:   # the same stock in several accounts: add the shares, average the cost
            known = [x for x in ((h["shares"], h["cost"]), (shares, cost)) if x[1] is not None]
            weight = sum(x[0] for x in known)
            h["cost"] = sum(a * b for a, b in known) / weight if known else None
            h["shares"] += shares
            h["accounts"] += 1
        else:
            holdings[sym] = {"symbol": sym, "name": name, "shares": shares, "cost": cost, "accounts": 1}
    used = [f"“{lines[header_at][c].strip()}” → {CSV_LABELS[f]}" for f, c in columns.items()]
    return {"holdings": list(holdings.values()), "skipped": skipped, "columns": used}


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


def load_settings():
    try:
        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_settings(settings):
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, indent=2)
    except OSError as exc:
        print(f"Couldn't save settings: {exc}")


SHORTCUTS = [
    ("Ctrl + 1 … 7", "Go to Home, Markets, News, Watchlist, Portfolio, Calendar or Bond Market"),
    ("Ctrl + F", "Jump to the search box on this page"),
    ("Esc  or  Alt + ←", "Go back (stock → market overview, news outlet → all news)"),
    ("←  /  →", "Change the chart range (1D … MAX) on the Markets page"),
    ("Ctrl + S", "Save a watermarked screenshot of this page's main chart"),
    ("F5  or  Ctrl + R", "Refresh this page"),
    ("Page Up / Page Down", "Scroll the page"),
    ("Home / End", "Jump to the top or bottom of the page"),
    ("F1", "Show this list"),
]


class SharedFetch:
    """Downloads something once for several pages and serves it from memory until it goes stale."""

    def __init__(self, worker, fn, max_age):
        self.worker, self.fn, self.max_age = worker, fn, max_age
        self.value, self.fetched, self.loading, self.waiters = None, None, False, []

    def get(self, on_done, on_error=None, force=False):
        fresh = self.value is not None and (datetime.now() - self.fetched).total_seconds() < self.max_age
        if fresh and not force:
            on_done(self.value)
            return
        self.waiters.append((on_done, on_error))
        if not self.loading:
            self.loading = True
            self.worker.run(self.fn, self._done, self._failed)

    def _done(self, value):
        self.value, self.fetched, self.loading = value, datetime.now(), False
        waiters, self.waiters = self.waiters, []
        for callback, _ in waiters:
            callback(value)

    def _failed(self, error):
        self.loading = False
        waiters, self.waiters = self.waiters, []
        for _, callback in waiters:
            if callback:
                callback(error)


class JsonList:
    """A list of records saved to a JSON file, telling listeners whenever it changes."""

    def __init__(self, path):
        self.path = path
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.items = data if isinstance(data, list) else []
        except (OSError, ValueError):
            self.items = []
        self.listeners = []

    def save(self):
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.items, f, indent=2)
        except OSError as exc:
            print(f"Couldn't save {os.path.basename(self.path)}: {exc}")
        for listener in list(self.listeners):
            try:
                listener()
            except tk.TclError:
                pass


class PortfolioStore(JsonList):
    """Holdings: symbol, name, shares and average cost per share."""

    def __init__(self):
        super().__init__(PORTFOLIO_FILE)

    @property
    def symbols(self):
        return [h["symbol"] for h in self.items]

    def set_holding(self, symbol, name, shares, cost):
        for h in self.items:
            if h["symbol"] == symbol:
                h.update(name=name or h.get("name", ""), shares=shares, cost=cost)
                break
        else:
            self.items.append({"symbol": symbol, "name": name, "shares": shares, "cost": cost})
        self.save()

    def remove(self, symbol):
        self.items = [h for h in self.items if h["symbol"] != symbol]
        self.save()

    def import_holdings(self, holdings, replace=False):
        """Add or update many holdings at once (one save). replace=True starts from an empty portfolio."""
        if replace:
            self.items = []
        existing = {h["symbol"]: h for h in self.items}
        for new in holdings:
            record = {"symbol": new["symbol"], "name": new.get("name", ""), "shares": new["shares"],
                      "cost": new.get("cost")}
            if new["symbol"] in existing:     # keep the name you already have; update shares and cost
                old = existing[new["symbol"]]
                old.update({k: v for k, v in record.items()
                            if v not in ("", None) and not (k == "name" and old.get("name"))})
            else:
                self.items.append(record)
        self.save()


class AlertStore(JsonList):
    """Price alerts. kind is "above", "below" or "move" (a % move in one day)."""

    def __init__(self):
        super().__init__(ALERTS_FILE)

    def add(self, symbol, name, kind, value):
        self.items.append({"id": f"{symbol}-{time.time():.0f}", "symbol": symbol, "name": name, "kind": kind,
                           "value": value, "created": datetime.now().isoformat(timespec="minutes"),
                           "triggered": None, "price": None})
        self.save()

    def remove(self, alert_id):
        self.items = [a for a in self.items if a["id"] != alert_id]
        self.save()

    def clear_triggered(self):
        self.items = [a for a in self.items if not a["triggered"]]
        self.save()

    def active(self):
        return [a for a in self.items if not a["triggered"]]


def describe_alert(alert):
    if alert["kind"] == "above":
        return f"Rises above {fmt_money(alert['value'])}"
    if alert["kind"] == "below":
        return f"Falls below {fmt_money(alert['value'])}"
    return f"Moves {alert['value']:g}% or more in a day"


def alert_hit(alert, quote):
    if alert["kind"] == "above":
        return quote["last"] >= alert["value"]
    if alert["kind"] == "below":
        return quote["last"] <= alert["value"]
    return abs(quote["pct"]) >= alert["value"]


_NOTIFY_ICON = None


def windows_notify(title, body):
    """A Windows toast notification (works while the app is minimized)."""
    global _NOTIFY_ICON
    try:
        if _NOTIFY_ICON is None:
            _NOTIFY_ICON = os.path.join(DATA_DIR, "notify_icon.png")
            if not os.path.exists(_NOTIFY_ICON):
                icon = Image.open(resource_path("assets", "icon.png"))
                icon.thumbnail((128, 128))
                icon.save(_NOTIFY_ICON)
    except Exception:
        _NOTIFY_ICON = ""

    def work():
        try:
            from win11toast import notify
            kwargs = {"icon": {"src": _NOTIFY_ICON, "placement": "appLogoOverride"}} if _NOTIFY_ICON else {}
            notify(title, body, **kwargs)
        except Exception as exc:
            print(f"Windows notification failed: {exc}")
    threading.Thread(target=work, daemon=True).start()
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


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


def set_index_ticks(ax, index, range_key):
    """~7 date labels for a chart plotted against bar number instead of date."""
    fmt = TICK_FORMATS[range_key]
    ticks = sorted(set(np.linspace(0, len(index) - 1, 7).round().astype(int)))
    ax.set_xticks(ticks)
    ax.set_xticklabels([index[i].strftime(fmt).lstrip("0") for i in ticks])
    tick_labels = ax.get_xticklabels()
    if len(tick_labels) > 1:
        tick_labels[0].set_horizontalalignment("left")
        tick_labels[-1].set_horizontalalignment("right")


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


def label(parent, text="", font="body", fg=None, bg=None, **kw):
    return tk.Label(parent, text=text, font=FONTS[font], fg=fg or INK, bg=bg or parent.cget("bg"), **kw)


def wrap_label(parent, text="", font="body", fg=None, **kw):
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


def card(parent, bg=None, border=True):
    return tk.Frame(parent, bg=bg or SURFACE, highlightthickness=1 if border else 0,
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


_LOGO = None


def _caption_font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def themed_logo():
    """The logo with transparent background; in dark mode its black lettering turns light."""
    logo = Image.open(resource_path("assets", "logo.png")).convert("RGBA")
    if THEME == "dark":
        pixels = np.array(logo)
        dark = pixels[..., :3].mean(axis=2) < 110
        pixels[dark, :3] = [int(INK[i:i + 2], 16) for i in (1, 3, 5)]
        logo = Image.fromarray(pixels)
    return logo


def add_watermark(img, caption=""):
    """Add a footer strip: caption on the left, the Insight by Milton logo in the bottom-right corner."""
    global _LOGO
    if _LOGO is None:
        _LOGO = themed_logo()
    img = img.convert("RGB")
    w, h = img.size
    logo_h = max(40, int(w * 0.04))
    logo = _LOGO.resize((int(_LOGO.width * logo_h / _LOGO.height), logo_h), Image.LANCZOS)
    margin = int(logo_h * 0.35)
    band = logo_h + margin
    out = Image.new("RGB", (w, h + band), BG)
    out.paste(img, (0, 0))
    draw = ImageDraw.Draw(out)
    draw.line([(margin, h), (w - margin, h)], fill=BORDER, width=max(1, logo_h // 40))
    out.paste(logo, (w - logo.width - margin // 2, h + margin // 2), logo)
    if caption:
        draw.text((margin, h + band / 2), caption, fill=MUTED, font=_caption_font(int(logo_h * 0.3)), anchor="lm")
    return out


def figure_image(fig):
    """Render a matplotlib figure at high resolution (hover crosshairs are left out)."""
    buffer = io.BytesIO()
    fig.savefig(buffer, format="png", dpi=200, facecolor=BG)
    buffer.seek(0)
    return Image.open(buffer)


def save_screenshot(app, image, name, caption=""):
    """Watermark an image and let the user choose where to save it."""
    pictures = os.path.join(os.path.expanduser("~"), "Pictures")
    filename = re.sub(r'[\\/:*?"<>|]', "", name).strip() + ".png"
    path = filedialog.asksaveasfilename(
        title="Save chart screenshot", defaultextension=".png", initialfile=filename,
        initialdir=pictures if os.path.isdir(pictures) else None,
        filetypes=[("PNG image", "*.png"), ("JPEG image", "*.jpg")])
    if not path:
        return
    try:
        add_watermark(image, caption).save(path, quality=95)
        app.set_status(f"Screenshot saved: {os.path.basename(path)}")
    except Exception as exc:
        app.set_status(f"Couldn't save the screenshot: {exc}")


def chart_caption(*parts):
    return "  ·  ".join([p for p in parts if p] + [short_date(datetime.now())])


class RoundButton(tk.Canvas):
    """Pill-shaped button like the 'Subscribe' button on the website."""
    @staticmethod
    def styles():  # fill, text, hover fill, outline — read at draw time so themes apply
        return {
            "primary": (ACCENT, BG, ACCENT_DARK, None),
            "dark": (INK, BG, blend(INK, BG, 0.2), None),
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
        fill, fg, hover, outline = self.styles()[self.kind]
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


class Skeleton(tk.Canvas):
    """Softly pulsing placeholder bars shown while content loads."""

    def __init__(self, parent, lines=3, line_height=12, gap=10, widths=(1.0, 0.86, 0.6)):
        height = lines * S(line_height) + (lines - 1) * S(gap)
        super().__init__(parent, height=height, bg=parent.cget("bg"), highlightthickness=0, bd=0)
        self.lines, self.lh, self.gap, self.widths = lines, S(line_height), S(gap), widths
        self.phase = 0.0
        self.bind("<Configure>", lambda e: self._draw())
        self.after(60, self._pulse)

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        shade = blend(SAND, BORDER, (math.sin(self.phase) + 1) / 2)
        for i in range(self.lines):
            y = i * (self.lh + self.gap)
            right = max(w * self.widths[i % len(self.widths)], self.lh)
            round_rect(self, 0, y, right, y + self.lh, self.lh / 2, fill=shade, outline=shade)

    def _pulse(self):
        try:
            if not self.winfo_exists():
                return
            self.phase += 0.22
            self._draw()
            self.after(60, self._pulse)
        except tk.TclError:
            pass


def show_skeleton(container, blocks=3, lines=3, pady=14):
    """Replace a container's contents with a few skeleton blocks."""
    for w in container.winfo_children():
        w.destroy()
    for i in range(blocks):
        Skeleton(container, lines=lines).pack(fill="x", pady=(S(pady), 0))


class ChartLoader:
    """A spinning ring laid over a chart while its data loads."""

    def __init__(self, host):
        self.host, self.canvas, self.job, self.angle, self.text = host, None, None, 0, ""

    def show(self, text="Loading…"):
        self.text = text
        if self.canvas is None:
            self.canvas = tk.Canvas(self.host, bg=BG, highlightthickness=0, bd=0)
        self.canvas.place(relx=0, rely=0, relwidth=1, relheight=1)
        if self.job is None:
            self._spin()

    def _spin(self):
        try:
            c = self.canvas
            c.delete("all")
            w, h = c.winfo_width(), c.winfo_height()
            r, cx, cy = S(16), w / 2, h / 2 - S(10)
            c.create_oval(cx - r, cy - r, cx + r, cy + r, outline=BORDER, width=S(3))
            c.create_arc(cx - r, cy - r, cx + r, cy + r, start=self.angle, extent=95, style="arc",
                         outline=ACCENT, width=S(3))
            c.create_text(cx, cy + r + S(18), text=self.text, fill=FAINT, font=FONTS["small"])
            self.angle = (self.angle - 14) % 360
            self.job = c.after(30, self._spin)
        except tk.TclError:
            self.job = None

    def hide(self):
        if self.job is not None and self.canvas is not None:
            try:
                self.canvas.after_cancel(self.job)
            except tk.TclError:
                pass
        self.job = None
        if self.canvas is not None:
            self.canvas.place_forget()


class ThemeToggle(tk.Canvas):
    """Round sun / moon button that switches between light and dark mode."""

    def __init__(self, parent, command):
        size = S(34)
        super().__init__(parent, width=size, height=size, bg=parent.cget("bg"), highlightthickness=0,
                         bd=0, cursor="hand2")
        self.command, self.hover = command, False
        self.bind("<Enter>", lambda e: self._set(True))
        self.bind("<Leave>", lambda e: self._set(False))
        self.bind("<ButtonRelease-1>", lambda e: self.command())
        self._draw()
        Tooltip(self, "Switch to light mode" if THEME == "dark" else "Switch to dark mode")

    def _set(self, hover):
        self.hover = hover
        self._draw()

    def _draw(self):
        self.delete("all")
        s = int(self["width"])
        ring = SAND if self.hover else self["bg"]
        self.create_oval(1, 1, s - 2, s - 2, fill=ring, outline=FAINT if self.hover else BORDER)
        c = s / 2
        if THEME == "dark":   # sun: switch back to light
            r = s * 0.14
            self.create_oval(c - r, c - r, c + r, c + r, fill=INK, outline=INK)
            for i in range(8):
                a = i * math.pi / 4
                self.create_line(c + math.cos(a) * s * 0.22, c + math.sin(a) * s * 0.22,
                                 c + math.cos(a) * s * 0.31, c + math.sin(a) * s * 0.31,
                                 fill=INK, width=max(1, S(1.6)), capstyle="round")
        else:                 # moon: switch to dark
            r = s * 0.24
            self.create_oval(c - r, c - r, c + r, c + r, fill=INK, outline=INK)
            off = s * 0.13
            self.create_oval(c - r + off, c - r - off * 0.6, c + r + off, c + r - off * 0.6, fill=ring, outline=ring)


KNOWN_NAMES = dict(BIG_STOCKS)
KNOWN_NAMES.update({sym: name for name, sym in INDEXES})
KNOWN_NAMES.update({sym: f"{name} Select Sector SPDR" for name, sym in SECTORS})
KNOWN_NAMES.update({"SPY": "SPDR S&P 500 ETF Trust", "QQQ": "Invesco QQQ Trust (Nasdaq-100)",
                    "DIA": "SPDR Dow Jones Industrial Average ETF", "IWM": "iShares Russell 2000 ETF",
                    "VOO": "Vanguard S&P 500 ETF", "BTC-USD": "Bitcoin", "ETH-USD": "Ethereum",
                    "GC=F": "Gold futures", "CL=F": "Crude oil futures", "^TNX": "10-Year Treasury yield"})


def search_suggestions(query):
    """Yahoo Finance's search-as-you-type results, cached for 10 minutes."""
    def fetch():
        items = []
        for q in yf.Search(query, max_results=8, news_count=0).quotes or []:
            if q.get("symbol"):
                items.append({"symbol": q["symbol"], "name": q.get("shortname") or q.get("longname") or "",
                              "detail": " · ".join(x for x in (q.get("exchDisp"), q.get("typeDisp")) if x)})
        return items
    return _cached(("suggest", query.lower()), 10 * 60, fetch) or []


class Suggester:
    """Dropdown of matching stocks under a search box. Arrow keys + Enter, or click, to pick."""

    def __init__(self, app, search, on_pick):
        self.app, self.search, self.on_pick = app, search, on_pick
        self.popup, self.items, self.index, self.job, self.request = None, [], -1, None, 0
        app.suggesters.append(self)
        e = search.entry
        e.bind("<KeyRelease>", self._on_key, add="+")
        e.bind("<FocusIn>", lambda ev: self._schedule(), add="+")
        e.bind("<FocusOut>", lambda ev: e.after(200, self._close_if_unfocused), add="+")
        e.bind("<Down>", lambda ev: self._move(1))
        e.bind("<Up>", lambda ev: self._move(-1))
        e.bind("<Return>", self._on_return)
        e.bind("<Escape>", self._on_escape)

    # --- suggestions ---------------------------------------------------------------
    def _on_key(self, event):
        if event.keysym not in ("Up", "Down", "Return", "Escape", "Tab", "Shift_L", "Shift_R",
                                "Control_L", "Control_R"):
            self._schedule()

    def _schedule(self):
        if self.job:
            self.search.after_cancel(self.job)
        self.job = self.search.after(140, self._update)

    def _local(self, query):
        names = dict(KNOWN_NAMES)
        names.update({i["symbol"]: i.get("name") or names.get(i["symbol"], "") for i in self.app.watchlist.items})
        recent = self.app.settings.get("recent", [])
        if not query:
            return [{"symbol": s, "name": names.get(s, ""), "detail": "Recent"} for s in recent[:6]]
        q = query.lower()
        found = []
        for sym, name in names.items():
            words = name.lower().split()
            if sym.lower().startswith(q) or any(w.startswith(q) for w in words) or name.lower().startswith(q):
                found.append({"symbol": sym, "name": name, "detail": "Recent" if sym in recent else ""})
        found.sort(key=lambda i: (i["symbol"].lower() != q, not i["symbol"].lower().startswith(q), i["symbol"]))
        return found[:5]

    def _update(self):
        self.job = None
        if self.app.focus_get() is not self.search.entry:
            return
        query = self.search.get()
        local = self._local(query)
        self._show(local)
        if query:
            self.request += 1
            rid = self.request
            self.app.worker.run(lambda: search_suggestions(query),
                                lambda remote: rid == self.request and self._merge(query, local, remote),
                                lambda e: None)

    def _merge(self, query, local, remote):
        seen, merged = set(), []
        exact = [i for i in local + remote if i["symbol"].lower() == query.lower()]
        for item in exact + remote + local:
            if item["symbol"] not in seen:
                seen.add(item["symbol"])
                merged.append(item)
        self._show(merged[:8])

    # --- popup -------------------------------------------------------------------------
    def _show(self, items):
        if not items or self.app.focus_get() is not self.search.entry:
            self.close()
            return
        self.items, self.index = items, -1
        if self.popup is None:
            self.popup = tk.Toplevel(self.app)
            self.popup.wm_overrideredirect(True)
            self.popup.configure(bg=BORDER)
            self.box = tk.Frame(self.popup, bg=SURFACE)
            self.box.pack(fill="both", expand=True, padx=1, pady=1)
        for w in self.box.winfo_children():
            w.destroy()
        self.rows = []
        if not self.search.get():
            label(self.box, "RECENT SEARCHES", "eyebrow", fg=FAINT, bg=SURFACE).pack(anchor="w", padx=S(14),
                                                                                     pady=(S(8), S(2)))
        for i, item in enumerate(items):
            row = tk.Frame(self.box, bg=SURFACE, cursor="hand2")
            row.pack(fill="x")
            label(row, item["symbol"], "body_semi", width=9, anchor="w").pack(side="left", padx=(S(14), 0), pady=S(7))
            name = item["name"] if len(item["name"]) <= 38 else item["name"][:37] + "…"
            label(row, name, "body", fg=MUTED).pack(side="left")
            if item.get("detail"):
                label(row, item["detail"], "small", fg=FAINT).pack(side="right", padx=S(14))
            for w in descendants(row):
                w.bind("<Button-1>", lambda e, k=i: self.pick(k))
                w.bind("<Enter>", lambda e, k=i: self._highlight(k))
            self.rows.append(row)
        frame = self.search
        frame.update_idletasks()
        width = max(frame.winfo_width(), S(440))
        x = frame.winfo_rootx() + frame.winfo_width() - width
        y = frame.winfo_rooty() + frame.winfo_height() + S(4)
        self.popup.geometry(f"{width}x{self.box.winfo_reqheight() + 2}+{x}+{y}")
        self.popup.lift()

    def _highlight(self, index):
        self.index = index
        for i, row in enumerate(self.rows):
            set_bg(row, SAND if i == index else SURFACE)

    def _move(self, step):
        if self.popup is None or not self.items:
            return "break"
        self._highlight((self.index + step) % len(self.items))
        return "break"

    def _on_return(self, event):
        if self.popup is not None and self.index >= 0:
            self.pick(self.index)
        else:
            self.close()
            if self.search.on_submit:
                self.search.on_submit()
        return "break"

    def _on_escape(self, event):
        if self.popup is not None:
            self.close()
            return "break"

    def pick(self, index):
        symbol = self.items[index]["symbol"]
        self.close()
        self.search.clear()
        self.app.focus_set()
        self.on_pick(symbol)

    def _close_if_unfocused(self):
        try:
            if self.app.focus_get() is not self.search.entry:
                self.close()
        except (KeyError, tk.TclError):
            self.close()

    def close(self):
        if self.popup is not None:
            try:
                self.popup.destroy()
            except tk.TclError:
                pass
            self.popup = None
        self.index = -1


def send_feedback(kind, message, name=""):
    """Open the user's email app with the suggestion ready to send."""
    subject = f"Insight by Milton — {kind}"
    body = f"{message.strip()}\n\n— {name.strip() or 'An Insight by Milton user'}\nSent from Insight by Milton v{VERSION}"
    url = f"mailto:{CONTACT_EMAIL}?subject={quote(subject)}&body={quote(body)}"
    try:
        os.startfile(url)
    except (AttributeError, OSError):
        webbrowser.open(url)


class FeedbackForm(tk.Frame):
    """Type of feedback, a message box and a Send button (used on Home and in the popup)."""

    def __init__(self, parent, on_sent=None, lines=5):
        bg = parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.on_sent = on_sent
        self.kind = ChipGroup(self, ["Idea", "Bug report", "Other"], value="Idea")
        self.kind.pack(anchor="w")
        border = tk.Frame(self, bg=SURFACE, highlightthickness=1, highlightbackground=BORDER)
        border.pack(fill="x", pady=(S(10), S(8)))
        self.text = tk.Text(border, height=lines, wrap="word", relief="flat", bd=0, bg=SURFACE, fg=INK,
                            insertbackground=INK, font=FONTS["body"], padx=S(12), pady=S(10))
        self.text.pack(fill="both", expand=True)
        self.text.bind("<FocusIn>", lambda e: border.configure(highlightbackground=ACCENT))
        self.text.bind("<FocusOut>", lambda e: border.configure(highlightbackground=BORDER))
        bottom = tk.Frame(self, bg=bg)
        bottom.pack(fill="x")
        self.name = SearchEntry(bottom, "Your name (optional)", width=22)
        self.name.pack(side="left")
        RoundButton(bottom, "Send", self.send).pack(side="right")
        self.note = label(self, "Opens your email app with the message ready — just press Send.", "small", fg=FAINT)
        self.note.pack(anchor="w", pady=(S(8), 0))

    def send(self):
        message = self.text.get("1.0", "end").strip()
        if not message:
            self.note.configure(text="Write your idea first, then press Send.", fg=DOWN)
            self.text.focus_set()
            return
        send_feedback(self.kind.selected or "Idea", message, self.name.get())
        self.text.delete("1.0", "end")
        self.note.configure(text="Thanks! Your email app is opening with your message — press Send there.", fg=UP)
        if self.on_sent:
            self.on_sent()


class FeedbackDialog(tk.Toplevel):
    instance = None

    @classmethod
    def open(cls, app):
        try:
            if cls.instance is not None and cls.instance.winfo_exists():
                cls.instance.lift()
                return
        except tk.TclError:
            pass
        cls.instance = cls(app)

    def __init__(self, app):
        super().__init__(app, bg=BG)
        self.title("Send an idea — Insight by Milton")
        self.transient(app)
        self.resizable(False, False)
        box = tk.Frame(self, bg=BG)
        box.pack(fill="both", expand=True, padx=S(30), pady=S(26))
        label(box, "Have an idea?", "h2").pack(anchor="w")
        wrap_label(box, "Suggest a feature, report a bug or tell us what you'd like to see in Insight by Milton.",
                   "small", fg=MUTED).pack(fill="x", pady=(S(4), S(14)))
        FeedbackForm(box, on_sent=lambda: self.after(2500, self.destroy), lines=7).pack(fill="x")
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        w = max(self.winfo_reqwidth(), S(560))
        x = app.winfo_rootx() + (app.winfo_width() - w) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"{w}x{self.winfo_reqheight()}+{x}+{y}")
        set_dark_titlebar(self, THEME == "dark")


class CameraButton(tk.Canvas):
    """Round camera-icon button that saves a watermarked screenshot of a chart."""

    def __init__(self, parent, command, tip="Save a screenshot of this chart"):
        size = S(32)
        super().__init__(parent, width=size, height=size, bg=parent.cget("bg"), highlightthickness=0,
                         bd=0, cursor="hand2")
        self.keep_bg = True
        self.command, self.hover = command, False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", lambda e: self.command())
        self._draw()
        Tooltip(self, tip)

    def _set_hover(self, value):
        self.hover = value
        self._draw()

    def _draw(self):
        self.delete("all")
        s = int(self["width"])
        ring = SAND if self.hover else self["bg"]
        self.create_oval(1, 1, s - 2, s - 2, fill=ring, outline=FAINT if self.hover else BORDER)
        c, bw, bh = s / 2, s * 0.48, s * 0.32
        x0, y0, x1, y1 = c - bw / 2, c - bh / 2 + s * 0.05, c + bw / 2, c + bh / 2 + s * 0.05
        self.create_rectangle(c - bw * 0.2, y0 - s * 0.08, c + bw * 0.2, y0 + 1, fill=INK, outline=INK)
        round_rect(self, x0, y0, x1, y1, s * 0.07, fill=INK, outline=INK)
        cy, r = (y0 + y1) / 2, bh * 0.34
        self.create_oval(c - r, cy - r, c + r, cy + r, fill=ring, outline=ring)
        r *= 0.5
        self.create_oval(c - r, cy - r, c + r, cy + r, fill=INK, outline=INK)


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
        self.on_submit = on_submit
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

    def set(self, text):
        self.entry.delete(0, "end")
        self.entry.insert(0, text)
        self.entry.configure(fg=INK)
        self.showing_placeholder = False


class ScrollFrame(tk.Frame):
    """A vertically scrolling page. Put content in .inner."""

    def __init__(self, parent, bg=None):
        bg = bg or BG
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

    def __init__(self, parent, height, width=None, bg=None, placeholder=""):
        bg = bg or SAND
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


def blend(color, other, amount):
    """Mix two hex colours; amount=0 gives color, 1 gives other."""
    a = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(other[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * amount):02x}" for x, y in zip(a, b))


def source_badge(parent, src, font="eyebrow", padx=5, pady=1, width=5):
    badge = label(parent, src["short"], font, fg="#FFFFFF", bg=src["color"], padx=S(padx), pady=S(pady),
                  width=width)
    badge.keep_bg = True
    return badge


class BiasScale(tk.Canvas):
    """Five-step Left → Right scale with the outlet's AllSides rating highlighted."""

    def __init__(self, parent, rating, width=400, compact=False):
        self.rating, self.compact = rating, compact
        height = S(12) if compact else S(70)
        super().__init__(parent, width=S(width), height=height, bg=parent.cget("bg"),
                         highlightthickness=0, bd=0)
        self.keep_bg = not compact
        self.bind("<Configure>", lambda e: self._draw())

    def _draw(self):
        self.delete("all")
        w = self.winfo_width()
        if w < 20:
            return
        gap = S(2) if self.compact else S(4)
        seg = (w - gap * 4) / 5
        top, bottom = (S(2), S(10)) if self.compact else (S(20), S(36))
        for i, step in enumerate(BIAS_SCALE):
            x = i * (seg + gap)
            on = step == self.rating
            color = BIAS_COLORS[step] if on else blend(BIAS_COLORS[step], self.cget("bg"), 0.68)
            round_rect(self, x, top, x + seg, bottom, S(3), fill=color, outline=color)
            if not self.compact:
                self.create_text(x + seg / 2, S(52), text=step, fill=INK if on else FAINT,
                                 font=FONTS["small_semi" if on else "small"])
                if on:
                    cx = x + seg / 2
                    self.create_polygon(cx - S(7), S(4), cx + S(7), S(4), cx, S(15), fill=INK, outline=INK)


class HeadlineRow(tk.Frame):
    """Text-only headline: source badge, outlet, bias, time, title and summary.
    Clicking the headline opens the article on the publisher's site; clicking the outlet opens
    its source page inside the app."""

    def __init__(self, parent, app, article, bg=None, summary=True, show_source=True):
        bg = bg or BG
        super().__init__(parent, bg=bg)
        src = SOURCES_BY_ID[article["source"]]
        inner = tk.Frame(self, bg=bg)
        inner.pack(fill="x", padx=S(8), pady=S(11))
        meta = tk.Frame(inner, bg=bg)
        meta.pack(fill="x")
        source_links = []
        if show_source:
            badge = source_badge(meta, src)
            badge.pack(side="left", padx=(0, S(8)))
            name = label(meta, src["name"], "small_semi")
            name.pack(side="left")
            label(meta, f"  {src['bias']}", "small", fg=bias_text_color(src["bias"])).pack(side="left")
            label(meta, "  ·  ", "small", fg=FAINT).pack(side="left")
            source_links = [badge, name]
        label(meta, time_ago(article["date"]) if article["date"] else "", "small", fg=FAINT).pack(side="left")
        visited = article["link"] in app.visited
        title = wrap_label(inner, article["title"], "card_title", fg=MUTED if visited else INK)
        title.pack(fill="x", pady=(S(4), 0))
        if visited:
            label(meta, "  ·  Read", "small", fg=FAINT).pack(side="left")

        def read():
            app.visited.add(article["link"])
            title.configure(fg=MUTED)
            open_link(article["link"])
        if summary and article["summary"]:
            text = article["summary"]
            text = text[:180].rsplit(" ", 1)[0] + "…" if len(text) > 180 else text
            wrap_label(inner, text, "small", fg=MUTED).pack(fill="x", pady=(S(3), 0))
        divider(self)
        make_clickable(self, read)
        for w in source_links:
            w.unbind("<Button-1>")
            w.bind("<Button-1>", lambda e: app.show_source(src["id"]))
        add_hover(self, lambda: set_bg(self, SAND), lambda: set_bg(self, bg))


class ShortcutsDialog(tk.Toplevel):
    """Small popup listing the keyboard shortcuts."""
    instance = None

    @classmethod
    def open(cls, app):
        try:
            if cls.instance is not None and cls.instance.winfo_exists():
                cls.instance.lift()
                return
        except tk.TclError:
            pass
        cls.instance = cls(app)

    def __init__(self, app):
        super().__init__(app, bg=BG)
        self.title("Keyboard shortcuts — Insight by Milton")
        self.transient(app)
        self.resizable(False, False)
        box = tk.Frame(self, bg=BG)
        box.pack(fill="both", expand=True, padx=S(32), pady=S(26))
        label(box, "Keyboard Shortcuts", "h2").pack(anchor="w", pady=(0, S(12)))
        for keys, action in SHORTCUTS:
            divider(box)
            row = tk.Frame(box, bg=BG)
            row.pack(fill="x", pady=S(7))
            label(row, keys, "small_semi", width=22, anchor="w").pack(side="left")
            label(row, action, "small", fg=MUTED).pack(side="left")
        divider(box)
        RoundButton(box, "Close", self.destroy, kind="dark").pack(anchor="e", pady=(S(16), 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_width()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_height()) // 3
        self.geometry(f"+{x}+{y}")
        self.focus_set()


class AlertDialog(tk.Toplevel):
    """Set a price alert for one stock."""
    KINDS = {"Rises above": "above", "Falls below": "below", "Moves ±% in a day": "move"}

    def __init__(self, app, symbol, name, price):
        super().__init__(app, bg=BG)
        self.app, self.symbol, self.name, self.price = app, symbol, name, price
        self.title(f"Price alert — {symbol}")
        self.transient(app)
        self.resizable(False, False)
        box = tk.Frame(self, bg=BG)
        box.pack(fill="both", expand=True, padx=S(30), pady=S(24))
        label(box, f"Price alert for {symbol}", "h2").pack(anchor="w")
        label(box, f"{name}  ·  now {fmt_price(price)}" if price else name, "small", fg=MUTED).pack(anchor="w")
        label(box, "NOTIFY ME WHEN THE PRICE", "eyebrow", fg=ACCENT).pack(anchor="w", pady=(S(18), S(8)))
        self.kind = ChipGroup(box, list(self.KINDS), self._kind_changed, value="Rises above")
        self.kind.pack(anchor="w")
        row = tk.Frame(box, bg=BG)
        row.pack(fill="x", pady=(S(14), S(6)))
        self.value = SearchEntry(row, "Price", self.save, width=16)
        self.value.pack(side="left")
        self.unit = label(row, "US$", "body", fg=MUTED)
        self.unit.pack(side="left", padx=S(10))
        self.note = label(box, "You'll get a Windows notification while Insight by Milton is open (it can be "
                               "minimized). Prices are checked every minute.", "small", fg=FAINT,
                          wraplength=S(460), justify="left")
        self.note.pack(anchor="w", pady=(S(4), S(14)))
        buttons = tk.Frame(box, bg=BG)
        buttons.pack(fill="x")
        RoundButton(buttons, "Save alert", self.save).pack(side="right")
        RoundButton(buttons, "Cancel", self.destroy, kind="ghost").pack(side="right", padx=S(10))
        existing = [a for a in app.alerts.active() if a["symbol"] == symbol]
        if existing:
            label(box, "ACTIVE ALERTS", "eyebrow", fg=FAINT).pack(anchor="w", pady=(S(18), S(4)))
            for a in existing:
                label(box, "•  " + describe_alert(a), "small").pack(anchor="w")
        self._kind_changed("Rises above")
        self.bind("<Escape>", lambda e: self.destroy())
        self.update_idletasks()
        x = app.winfo_rootx() + (app.winfo_width() - self.winfo_reqwidth()) // 2
        y = app.winfo_rooty() + (app.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{x}+{y}")
        set_dark_titlebar(self, THEME == "dark")
        self.value.focus()

    def _kind_changed(self, choice):
        kind = self.KINDS[choice]
        if kind == "move":
            self.value.set("3")
            self.unit.configure(text="% up or down")
        else:
            self.value.set(f"{self.price * (1.05 if kind == 'above' else 0.95):.2f}" if self.price else "")
            self.unit.configure(text="US$")

    def save(self):
        try:
            value = float(self.value.get().replace("$", "").replace(",", "").replace("%", ""))
            assert value > 0
        except (ValueError, AssertionError):
            self.note.configure(text="Enter a number greater than zero.", fg=DOWN)
            return
        self.app.alerts.add(self.symbol, self.name, self.KINDS[self.kind.selected], value)
        self.app.set_status(f"Alert saved: {self.symbol} — {describe_alert(self.app.alerts.items[-1]).lower()}")
        self.destroy()


class ImportDialog(tk.Toplevel):
    """Preview a CSV before importing it into the portfolio."""

    def __init__(self, app, path):
        super().__init__(app, bg=BG)
        self.app, self.path = app, path
        self.title("Import portfolio from CSV — Insight by Milton")
        self.transient(app)
        w, h = min(S(820), int(app.winfo_width() * 0.9)), min(S(720), int(app.winfo_height() * 0.9))
        self.geometry(f"{w}x{h}+{app.winfo_rootx() + (app.winfo_width() - w) // 2}"
                      f"+{app.winfo_rooty() + (app.winfo_height() - h) // 3}")
        set_dark_titlebar(self, THEME == "dark")
        self.bind("<Escape>", lambda e: self.destroy())

        head = tk.Frame(self, bg=BG)
        head.pack(fill="x", padx=S(30), pady=(S(24), S(10)))
        label(head, "Import portfolio", "page_title").pack(anchor="w")
        label(head, os.path.basename(path), "small", fg=MUTED).pack(anchor="w")

        foot = tk.Frame(self, bg=BG)
        foot.pack(fill="x", side="bottom")
        tk.Frame(foot, bg=BORDER, height=1).pack(fill="x")
        self.buttons = tk.Frame(foot, bg=BG)
        self.buttons.pack(fill="x", padx=S(30), pady=S(14))
        RoundButton(self.buttons, "Cancel", self.destroy, kind="ghost").pack(side="right")

        try:
            self.result = parse_portfolio_csv(path)
        except Exception as exc:
            msg = str(exc) if isinstance(exc, ValueError) else f"Couldn't read this file ({exc})."
            wrap_label(head, msg, "body", fg=DOWN).pack(fill="x", pady=(S(16), S(8)))
            wrap_label(head, "A simple file works too — for example:\n\nSymbol,Shares,Average Cost\n"
                             "AAPL,10,180\nMSFT,5,400", "small", fg=MUTED).pack(fill="x")
            return
        holdings = self.result["holdings"]
        if not holdings:
            wrap_label(head, "No holdings were found in this file.", "body", fg=DOWN).pack(fill="x", pady=S(16))
            return

        existing = set(app.portfolio.symbols)
        updates = sum(1 for h in holdings if h["symbol"] in existing)
        missing_cost = sum(1 for h in holdings if h["cost"] is None)
        summary = f"Found {len(holdings)} holding{'s' if len(holdings) != 1 else ''}"
        if updates:
            summary += f" · {updates} already in your portfolio"
        if self.result["skipped"]:
            summary += f" · skipped {len(self.result['skipped'])} other row{'s' if len(self.result['skipped']) != 1 else ''}"
        label(head, summary, "body_semi").pack(anchor="w", pady=(S(12), S(2)))
        wrap_label(head, "Columns used: " + ";  ".join(self.result["columns"]), "small", fg=FAINT).pack(fill="x")

        mode = tk.Frame(head, bg=BG)
        mode.pack(fill="x", pady=(S(14), 0))
        self.mode = ChipGroup(mode, ["Add & update", "Replace all"], self._mode_changed, value="Add & update")
        self.mode.pack(side="left")
        self.mode_note = label(mode, "", "small", fg=MUTED)
        self.mode_note.pack(side="left", padx=S(14))
        self._mode_changed("Add & update")

        tk.Frame(self, bg=BORDER, height=1).pack(fill="x")
        scroller = ScrollFrame(self)
        scroller.pack(fill="both", expand=True)
        table = tk.Frame(scroller.inner, bg=BG)
        table.pack(fill="x", padx=S(30), pady=S(10))
        heads = [("SYMBOL", "w", 90), ("NAME", "w", 0), ("SHARES", "e", 90), ("AVG COST", "e", 100), ("", "e", 120)]
        for c, (title, anchor, width) in enumerate(heads):
            table.columnconfigure(c, minsize=S(width), weight=1 if c == 1 else 0)
            label(table, title, "eyebrow", fg=FAINT).grid(row=0, column=c, sticky=anchor, padx=S(6), pady=(0, S(6)))
        for r, h in enumerate(holdings, start=1):
            name = h["name"] if len(h["name"]) <= 40 else h["name"][:39] + "…"
            status = ("Updates existing" if h["symbol"] in existing else "New") + (
                f" · {h['accounts']} accounts" if h["accounts"] > 1 else "")
            cells = [(h["symbol"], "body_semi", INK), (name, "small", MUTED), (f"{h['shares']:,g}", "body", INK),
                     (fmt_money(h["cost"]) if h["cost"] is not None else "add later", "body",
                      INK if h["cost"] is not None else FAINT),
                     (status, "small", ACCENT if h["symbol"] in existing else FAINT)]
            for c, (text, font, fg) in enumerate(cells):
                label(table, text, font, fg=fg).grid(row=r, column=c, sticky=heads[c][1], padx=S(6), pady=S(4))
        if missing_cost:
            wrap_label(scroller.inner, f"{missing_cost} holding{'s have' if missing_cost != 1 else ' has'} no cost in "
                                       "the file — value and dividends still work; add the cost later with ✎ to see "
                                       "gains.", "small", fg=FAIR).pack(fill="x", padx=S(30), pady=(S(4), 0))
        if self.result["skipped"]:
            label(scroller.inner, "SKIPPED ROWS", "eyebrow", fg=FAINT).pack(anchor="w", padx=S(30), pady=(S(14), S(4)))
            for line, what, why in self.result["skipped"][:12]:
                label(scroller.inner, f"Line {line}:  {what or '(blank)'} — {why}", "small",
                      fg=FAINT).pack(anchor="w", padx=S(30))
            if len(self.result["skipped"]) > 12:
                label(scroller.inner, f"…and {len(self.result['skipped']) - 12} more", "small",
                      fg=FAINT).pack(anchor="w", padx=S(30))
        tk.Frame(scroller.inner, bg=BG, height=S(16)).pack()
        self.go = RoundButton(self.buttons, f"Import {len(holdings)} holding{'s' if len(holdings) != 1 else ''}",
                              self.do_import)
        self.go.pack(side="right", padx=S(10))

    def _mode_changed(self, choice):
        n = len(self.app.portfolio.items)
        self.mode_note.configure(
            text="Keeps your other holdings; matching symbols are updated." if choice == "Add & update" else
            f"Removes your current {n} holding{'s' if n != 1 else ''} and uses only this file.",
            fg=MUTED if choice == "Add & update" else DOWN)

    def do_import(self):
        replace = self.mode.selected == "Replace all"
        holdings = self.result["holdings"]
        self.app.portfolio.import_holdings(holdings, replace=replace)
        self.app.set_status(f"Imported {len(holdings)} holdings from {os.path.basename(self.path)}")
        self.destroy()


class CriteriaDialog(tk.Toplevel):
    """Popup explaining what every fundamental metric means and how it's colour-coded."""
    instance = None

    @classmethod
    def open(cls, app):
        try:
            if cls.instance is not None and cls.instance.winfo_exists():
                cls.instance.lift()
                cls.instance.focus_set()
                return
        except tk.TclError:
            pass
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
        self._build_feedback(wrap)
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
        RoundButton(buttons, "Explore Markets", lambda: self.app.navigate("Markets")).pack(side="left")
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
        make_clickable(more, lambda: self.app.navigate("Markets"))
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
        for i in range(3):
            self.insights.columnconfigure(i, weight=1, uniform="insight")
            holder = card(self.insights)
            holder.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else S(10), 0 if i == 2 else S(10)))
            tk.Frame(holder, bg=SAND, height=S(190)).pack(fill="x")
            Skeleton(holder, lines=4).pack(fill="x", padx=S(20), pady=S(20))

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
        Skeleton(self.movers_list, lines=7, line_height=14, gap=18, widths=(1.0,)).pack(fill="x", pady=S(8))

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

    # --- feedback ---------------------------------------------------------------
    def _build_feedback(self, parent):
        box = card(parent)
        box.pack(fill="x", pady=(S(28), 0))
        inner = tk.Frame(box, bg=SURFACE)
        inner.pack(fill="both", expand=True, padx=S(28), pady=S(24))
        inner.columnconfigure(0, weight=2, uniform="fb")
        inner.columnconfigure(1, weight=3, uniform="fb")
        text = tk.Frame(inner, bg=SURFACE)
        text.grid(row=0, column=0, sticky="nw", padx=(0, S(28)))
        label(text, "HAVE AN IDEA?", "eyebrow", fg=ACCENT).pack(anchor="w")
        label(text, "Help shape Insight by Milton", "h2").pack(anchor="w", pady=(S(4), S(8)))
        wrap_label(text, "Suggest a feature, report something that isn't working, or tell us what you'd "
                         "like to read about. Every message goes straight to The Milton Review.",
                   "body", fg=MUTED).pack(fill="x")
        FeedbackForm(inner, lines=3).grid(row=0, column=1, sticky="nsew")

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
        self.app.milton.get(self._show_insights, self._insights_failed)

    def refresh(self):
        self._load_snapshot()


# -------------------------------------------------------------- Markets ------
class MarketsPage(Page):
    refresh_ms = 60_000

    def build(self):
        self.range_key, self.overview_range = "1Y", "1M"
        self.mode = "overview"
        self.overview_id = 0
        self.hover_bg = None
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
        head = self.page_header(wrap, "Markets", "Today's market at a glance. Search any stock, ETF, index "
                                                 "or crypto by ticker or company name.")
        search = tk.Frame(head, bg=BG)
        search.pack(side="right", anchor="s")
        self.search = SearchEntry(search, "Search e.g. AAPL or Tesla", self.do_search, width=28)
        self.search.pack(side="left")
        self.suggest = Suggester(self.app, self.search, self.load)
        RoundButton(search, "Search", self.do_search).pack(side="left", padx=(S(10), 0))
        RoundButton(search, "Compare stocks", lambda: self.open_compare(), kind="ghost").pack(side="left", padx=(S(10), 0))

        popular = tk.Frame(wrap, bg=BG)
        popular.pack(fill="x", pady=(0, S(22)))
        label(popular, "POPULAR", "eyebrow", fg=FAINT).pack(side="left", padx=(0, S(12)))
        for sym in ("AAPL", "MSFT", "NVDA", "TSLA", "AMZN", "SPY", "QQQ", "BTC-USD"):
            chip = RoundButton(popular, sym, lambda s=sym: self.load(s), kind="chip", font="chip",
                               padx=12, pady=5, radius=12)
            chip.pack(side="left", padx=(0, S(6)))
            chip.bind("<Enter>", lambda e, s=sym: prefetch(s, self.range_key), add="+")
        self.recent_row = tk.Frame(popular, bg=BG)
        self.recent_row.pack(side="left", padx=(S(20), 0))
        self._render_recent()

        self.overview = tk.Frame(wrap, bg=BG)
        self.overview.pack(fill="both", expand=True)
        self._build_overview(self.overview)
        self.compare = tk.Frame(wrap, bg=BG)      # compare view, shown by open_compare()
        self._build_compare(self.compare)

        cols = tk.Frame(wrap, bg=BG)   # the single-stock detail view, shown by load()
        self.detail = cols
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, minsize=S(330))
        main = tk.Frame(cols, bg=BG)
        main.grid(row=0, column=0, sticky="nsew", padx=(0, S(28)))
        side = tk.Frame(cols, bg=BG)
        side.grid(row=0, column=1, sticky="nsew")
        back = label(main, "← Market overview", "body_semi", fg=ACCENT)
        back.pack(anchor="w", pady=(0, S(14)))
        make_clickable(back, self.show_overview)

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
        CameraButton(controls, self.save_chart).pack(side="right")
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
        self.canvas.mpl_connect("draw_event", self._save_background)
        self.loader = ChartLoader(chart)
        self.canvas.mpl_connect("figure_leave_event", lambda e: self._hide_hover())

        self.fund_section = tk.Frame(main, bg=BG)   # only packed for companies, see _fill_fundamentals
        self.headlines_title = label(main, "Related Financial News", "h2")
        self.headlines_title.pack(anchor="w", pady=(S(28), S(10)))
        self.news_box = tk.Frame(main, bg=BG)
        self.news_box.pack(fill="x")

        # sidebar
        self.watch_button = RoundButton(side, "+ Add to Watchlist", self.toggle_watch)
        self.watch_button.pack(anchor="w", pady=(S(4), S(8)))
        actions = tk.Frame(side, bg=BG)
        actions.pack(anchor="w", pady=(0, S(18)))
        RoundButton(actions, "Set price alert", self.open_alert, kind="ghost", font="chip", padx=12, pady=6,
                    radius=12).pack(side="left")
        RoundButton(actions, "Compare", lambda: self.open_compare([self.data["symbol"], "SPY"] if self.data else None),
                    kind="ghost", font="chip", padx=12, pady=6, radius=12).pack(side="left", padx=S(8))
        self.alert_note = label(side, "", "small", fg=FAINT)
        self.alert_note.pack(anchor="w", pady=(0, S(10)))
        self.app.alerts.listeners.append(self._update_alert_note)
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

    # --- market overview (default view) ------------------------------------------
    def _build_overview(self, parent):
        # index cards
        cards = tk.Frame(parent, bg=BG)
        cards.pack(fill="x")
        self.index_cards = {}
        for i, (name, sym) in enumerate(INDEXES):
            cards.columnconfigure(i, weight=1, uniform="idx")
            c = card(cards)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else S(8), 0 if i == 3 else S(8)))
            box = tk.Frame(c, bg=SURFACE)
            box.pack(fill="both", expand=True, padx=S(18), pady=S(14))
            top = tk.Frame(box, bg=SURFACE)
            top.pack(fill="x")
            dot = tk.Canvas(top, width=S(10), height=S(10), bg=SURFACE, highlightthickness=0)
            dot.create_oval(1, 1, S(9), S(9), fill=INDEX_COLORS[i], outline="")
            dot.pack(side="left", padx=(0, S(6)))
            label(top, name.upper(), "eyebrow", fg=MUTED).pack(side="left")
            value = label(box, "—", "card_value")
            value.pack(anchor="w", pady=(S(4), 0))
            change = label(box, " ", "small_semi", fg=MUTED)
            change.pack(anchor="w")
            make_clickable(c, lambda s=sym: self.load(s))
            hover_border(c)
            c.bind("<Enter>", lambda e, s=sym: prefetch(s, self.range_key), add="+")
            self.index_cards[sym] = (value, change)

        # comparison chart
        row = tk.Frame(parent, bg=BG)
        row.pack(fill="x", pady=(S(26), S(4)))
        label(row, "Major Indices", "h2").pack(side="left")
        CameraButton(row, self._screenshot_indices).pack(side="right", padx=(S(10), 0))
        ChipGroup(row, list(OVERVIEW_RANGES), self._set_overview_range,
                  value=self.overview_range).pack(side="right")
        self.overview_note = label(parent, "Percent change over the period — compare how each index has moved.",
                                   "small", fg=MUTED)
        self.overview_note.pack(anchor="w")
        self.index_fig = Figure(figsize=(9, 3.4), dpi=96 * SCALE, facecolor=BG)
        self.index_canvas = FigureCanvasTkAgg(self.index_fig, master=parent)
        w = self.index_canvas.get_tk_widget()
        w.configure(height=S(340), bg=BG, highlightthickness=0)
        w.pack(fill="x", pady=(S(6), 0))
        self.index_loader = ChartLoader(w)

        # sectors + largest companies
        lower = tk.Frame(parent, bg=BG)
        lower.pack(fill="x", pady=(S(28), 0))
        lower.columnconfigure(0, weight=2, uniform="lower")
        lower.columnconfigure(1, weight=3, uniform="lower")

        sec = card(lower)
        sec.grid(row=0, column=0, sticky="nsew", padx=(0, S(10)))
        sbox = tk.Frame(sec, bg=SURFACE)
        sbox.pack(fill="both", expand=True, padx=S(22), pady=S(18))
        sec_head = tk.Frame(sbox, bg=SURFACE)
        sec_head.pack(fill="x")
        label(sec_head, "Sector Performance", "h2").pack(side="left")
        CameraButton(sec_head, self._screenshot_sectors).pack(side="right")
        label(sbox, "S&P 500 sectors, today · click to open the sector ETF", "small", fg=MUTED).pack(anchor="w")
        self.sector_rows = {}
        rows = tk.Frame(sbox, bg=SURFACE)
        rows.pack(fill="x", pady=(S(10), 0))
        rows.columnconfigure(1, weight=1)
        for r, (name, sym) in enumerate(SECTORS):
            name_lbl = label(rows, name, "small", anchor="w")
            name_lbl.grid(row=r, column=0, sticky="w", pady=S(4), padx=(0, S(10)))
            bar = tk.Canvas(rows, height=S(14), bg=SURFACE, highlightthickness=0)
            bar.grid(row=r, column=1, sticky="ew")
            pct = label(rows, "", "small_semi", width=7, anchor="e")
            pct.grid(row=r, column=2, sticky="e", padx=(S(8), 0))
            for widget in (name_lbl, bar, pct):
                widget.bind("<Button-1>", lambda e, s=sym: self.load(s))
                widget.configure(cursor="hand2")
            bar.bind("<Configure>", lambda e, s=sym: self._draw_sector_bar(s))
            self.sector_rows[sym] = (bar, pct)
        self.sector_values = {}

        big = card(lower)
        big.grid(row=0, column=1, sticky="nsew", padx=(S(10), 0))
        bbox = tk.Frame(big, bg=SURFACE)
        bbox.pack(fill="both", expand=True, padx=S(22), pady=S(18))
        label(bbox, "Largest Companies", "h2").pack(anchor="w")
        label(bbox, "Click any company for its full chart, statistics and fundamentals", "small",
              fg=MUTED).pack(anchor="w", pady=(0, S(8)))
        self.big_rows = {}
        for sym, name in BIG_STOCKS:
            divider(bbox)
            r = tk.Frame(bbox, bg=SURFACE)
            r.pack(fill="x")
            r.columnconfigure(1, weight=1)
            label(r, sym, "body_semi", width=7, anchor="w").grid(row=0, column=0, sticky="w", pady=S(6), padx=(S(4), 0))
            label(r, name, "body", fg=MUTED, anchor="w").grid(row=0, column=1, sticky="w")
            price = label(r, "…", "body", width=9, anchor="e")
            price.grid(row=0, column=2, sticky="e")
            pill_box = tk.Frame(r, bg=SURFACE)
            pill_box.grid(row=0, column=3, sticky="e", padx=S(12))
            spark = Sparkline(r, height=24, width=110)
            spark.grid(row=0, column=4, sticky="e", padx=(0, S(4)))
            make_clickable(r, lambda s=sym: self.load(s))
            add_hover(r, lambda r=r, s=sym: (set_bg(r, SAND), prefetch(s, self.range_key)),
                      lambda r=r: set_bg(r, SURFACE))
            self.big_rows[sym] = (price, pill_box, spark)

    def _draw_sector_bar(self, sym):
        bar, _ = self.sector_rows[sym]
        bar.delete("all")
        pct = self.sector_values.get(sym)
        w, h = bar.winfo_width(), bar.winfo_height()
        if pct is None or w < 10:
            return
        scale = max((abs(v) for v in self.sector_values.values()), default=1) or 1
        mid = w / 2
        bar.create_line(mid, 0, mid, h, fill=BORDER)
        length = (w / 2 - S(2)) * abs(pct) / scale
        x0, x1 = (mid, mid + length) if pct >= 0 else (mid - length, mid)
        bar.create_rectangle(x0, S(2), x1, h - S(2), fill=UP if pct >= 0 else DOWN, outline="")

    def _load_overview(self):
        symbols = [s for _, s in INDEXES] + [s for _, s in SECTORS] + [s for s, _ in BIG_STOCKS]
        self.app.worker.run(lambda: fetch_quotes(symbols), self._show_overview_quotes,
                            lambda e: self.overview_note.configure(
                                text="Couldn't reach Yahoo Finance — retrying in a minute.", fg=DOWN))
        self._load_index_chart()

    def _show_overview_quotes(self, quotes):
        for sym, (value, change) in self.index_cards.items():
            q = quotes.get(sym)
            if q:
                value.configure(text=fmt_price(q["last"]))
                change.configure(text=f"{fmt_change(q['change'])}  ({fmt_pct(q['pct'])})",
                                 fg=trend_color(q["change"]))
        self.sector_values = {s: quotes[s]["pct"] for _, s in SECTORS if s in quotes}
        for sym, (bar, pct) in self.sector_rows.items():
            v = self.sector_values.get(sym)
            pct.configure(text=fmt_pct(v) if v is not None else "—", fg=trend_color(v))
            self._draw_sector_bar(sym)
        for sym, (price, pill_box, spark) in self.big_rows.items():
            q = quotes.get(sym)
            if not q:
                continue
            price.configure(text=fmt_price(q["last"]))
            for w in pill_box.winfo_children():
                w.destroy()
            change_pill(pill_box, q["pct"], width=8).pack()
            spark.set(q["spark"], trend_color(q["change"]))

    def _screenshot_indices(self):
        caption = chart_caption("Major U.S. stock indices", f"% change, {self.overview_range}")
        save_screenshot(self.app, figure_image(self.index_fig), f"Major indices {self.overview_range}", caption)

    def _screenshot_sectors(self):
        """The sector bars are Tk widgets, so draw the same chart with matplotlib for the image."""
        if not self.sector_values:
            return
        names = [n for n, sym in SECTORS if sym in self.sector_values][::-1]
        values = [self.sector_values[sym] for _, sym in SECTORS if sym in self.sector_values][::-1]
        fig = Figure(figsize=(8, 4.6), facecolor=BG)
        ax = fig.add_subplot(111)
        style_axes(ax)
        ax.grid(True, axis="x", color=BORDER, linewidth=0.8)
        ax.grid(False, axis="y")
        ax.barh(names, values, color=[UP if v >= 0 else DOWN for v in values], height=0.6)
        ax.axvline(0, color=FAINT, linewidth=0.9)
        span = max(abs(v) for v in values) or 1
        for y, v in enumerate(values):
            ax.text(v + (span * 0.03 if v >= 0 else -span * 0.03), y, fmt_pct(v), va="center",
                    ha="left" if v >= 0 else "right", fontsize=8.5, color=trend_color(v))
        ax.set_xlim(-span * 1.3, span * 1.3)
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:+.1f}%"))
        ax.tick_params(axis="y", labelsize=9, colors=INK)
        ax.set_title("S&P 500 Sector Performance — Today", loc="left", fontsize=12, color=INK, pad=12)
        fig.subplots_adjust(left=0.27, right=0.97, top=0.9, bottom=0.08)
        save_screenshot(self.app, figure_image(fig), "Sector performance",
                        chart_caption("S&P 500 sectors (SPDR sector ETFs)"))

    def _set_overview_range(self, range_key):
        self.overview_range = range_key
        self._load_index_chart()

    def _load_index_chart(self):
        self.overview_id += 1
        rid, rk = self.overview_id, self.overview_range
        self.index_loader.show("Loading indices…")
        self.app.worker.run(lambda: fetch_index_history(rk),
                            lambda df: self._draw_index_chart(rid, rk, df))

    def _draw_index_chart(self, rid, range_key, df):
        if rid != self.overview_id or df.empty:
            return
        self.index_loader.hide()
        fig = self.index_fig
        fig.clear()
        ax = fig.add_subplot(111)
        style_axes(ax, price_on_right=True)
        x = np.arange(len(df))
        for i, (name, sym) in enumerate(INDEXES):
            if sym not in df:
                continue
            series = df[sym].to_numpy()
            change = (series / series[0] - 1) * 100
            ax.plot(x, change, color=INDEX_COLORS[i], linewidth=1.8 if i == 0 else 1.4,
                    label=f"{name}  {change[-1]:+.2f}%")
        ax.axhline(0, color=FAINT, linewidth=0.8, linestyle=(0, (2, 3)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:+.0f}%" if abs(v) >= 5 else f"{v:+.1f}%"))
        ax.set_xlim(0, max(len(x) - 1, 1))
        set_index_ticks(ax, df.index, range_key)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=8, ncol=4,
                  labelcolor=MUTED, borderaxespad=0.2)
        fig.subplots_adjust(left=0.02, right=0.93, top=0.88, bottom=0.1)
        self.index_canvas.draw_idle()

    def show_overview(self):
        self.request_id += 1   # ignore any stock that was still loading
        self._set_mode("overview")
        self.app.set_status("")
        self.app.update_title()

    def _set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        for name, frame in (("overview", self.overview), ("detail", self.detail), ("compare", self.compare)):
            if name == mode:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        self.scroller.to_top()

    # --- price alerts ---------------------------------------------------------------
    def open_alert(self):
        if not self.data:
            return
        info = self.data["info"]
        AlertDialog(self.app, self.data["symbol"], info.get("shortName") or self.data["symbol"], self.last_price)

    def _update_alert_note(self):
        if not self.data:
            return
        n = sum(1 for a in self.app.alerts.active() if a["symbol"] == self.data["symbol"])
        self.alert_note.configure(text=f"{n} active price alert{'s' if n != 1 else ''} — see Watchlist" if n else "")

    # --- compare stocks -----------------------------------------------------------------
    COMPARE_RANGES = ["1M", "6M", "YTD", "1Y", "5Y"]
    COMPARE_COLORS = ["#D47A5D", "#5B7FA6", "#7E9B6A", "#C9A227", "#8E79AE"]
    COMPARE_ROWS = [("Price", None), ("Today", None), ("Period change", None), ("Market cap", None),
                    ("P/E (TTM)", "P/E (TTM)"), ("Forward P/E", "Forward P/E"), ("Profit margin", "Profit margin"),
                    ("Revenue growth", "Revenue growth"), ("Debt / Equity", "Debt / Equity"),
                    ("Dividend yield", None), ("Beta", None), ("Fundamentals", None)]

    def _build_compare(self, parent):
        self.compare_symbols, self.compare_range, self.compare_id = ["AAPL", "MSFT", "GOOGL"], "1Y", 0
        self.compare_data = {}
        back = label(parent, "← Market overview", "body_semi", fg=ACCENT)
        back.pack(anchor="w", pady=(0, S(14)))
        make_clickable(back, self.show_overview)
        top = tk.Frame(parent, bg=BG)
        top.pack(fill="x")
        label(top, "Compare Stocks", "h2").pack(side="left")
        add = tk.Frame(top, bg=BG)
        add.pack(side="right")
        self.compare_entry = SearchEntry(add, "Add a symbol to compare", self._compare_add_typed, width=24)
        self.compare_entry.pack(side="left")
        RoundButton(add, "Add", self._compare_add_typed).pack(side="left", padx=(S(10), 0))
        Suggester(self.app, self.compare_entry, self.compare_add)
        label(parent, "Up to 5 stocks, ETFs or crypto — percent change over the period, plus key numbers side by side.",
              "small", fg=MUTED).pack(anchor="w", pady=(S(2), S(12)))
        controls = tk.Frame(parent, bg=BG)
        controls.pack(fill="x")
        self.compare_chips = tk.Frame(controls, bg=BG)
        self.compare_chips.pack(side="left")
        CameraButton(controls, self._screenshot_compare).pack(side="right", padx=(S(10), 0))
        ChipGroup(controls, self.COMPARE_RANGES, self._compare_set_range, value=self.compare_range).pack(side="right")
        self.compare_fig = Figure(figsize=(9, 3.8), dpi=96 * SCALE, facecolor=BG)
        self.compare_canvas = FigureCanvasTkAgg(self.compare_fig, master=parent)
        w = self.compare_canvas.get_tk_widget()
        w.configure(height=S(380), bg=BG, highlightthickness=0)
        w.pack(fill="x", pady=(S(10), 0))
        self.compare_loader = ChartLoader(w)
        table = card(parent)
        table.pack(fill="x", pady=(S(20), 0))
        self.compare_table = tk.Frame(table, bg=SURFACE)
        self.compare_table.pack(fill="x", padx=S(14), pady=S(10))

    def open_compare(self, symbols=None):
        if symbols:
            self.compare_symbols = list(dict.fromkeys(s for s in symbols if s))[:5]
        if not self.loaded:
            self.loaded = True
            self._load_overview()
        self.request_id += 1
        self._set_mode("compare")
        self.app.update_title("Compare")
        self._compare_load()

    def compare_add(self, symbol):
        symbol = symbol.upper()
        if symbol in self.compare_symbols:
            return
        if len(self.compare_symbols) >= 5:
            self.app.set_status("You can compare up to 5 at once — remove one first.")
            return
        self.compare_symbols.append(symbol)
        self._compare_load()

    def _compare_add_typed(self):
        text = self.compare_entry.get()
        if not text:
            return
        self.compare_entry.clear()

        def resolve():
            sym = text.upper()
            if TICKER_RE.match(sym) and not fetch_history(sym, "1M").empty:
                return sym
            return search_symbol(text)[0]
        self.app.worker.run(resolve, self.compare_add,
                            lambda e: self.app.set_status(f"Couldn't find “{text}”."))

    def _compare_remove(self, symbol):
        self.compare_symbols = [s for s in self.compare_symbols if s != symbol]
        self._compare_load()

    def _compare_set_range(self, range_key):
        self.compare_range = range_key
        self._compare_load()

    def _render_compare_chips(self):
        for w in self.compare_chips.winfo_children():
            w.destroy()
        for i, sym in enumerate(self.compare_symbols):
            chip = tk.Frame(self.compare_chips, bg=SAND)
            chip.pack(side="left", padx=(0, S(8)))
            dot = tk.Canvas(chip, width=S(10), height=S(10), bg=SAND, highlightthickness=0)
            dot.create_oval(1, 1, S(9), S(9), fill=self.COMPARE_COLORS[i], outline="")
            dot.pack(side="left", padx=(S(10), S(6)), pady=S(6))
            label(chip, sym, "small_semi").pack(side="left")
            x = label(chip, "  ✕", "small", fg=FAINT, cursor="hand2")
            x.pack(side="left", padx=(0, S(10)))
            x.bind("<Button-1>", lambda e, s=sym: self._compare_remove(s))

    def _compare_load(self):
        self._render_compare_chips()
        self.compare_id += 1
        rid, symbols, rk = self.compare_id, list(self.compare_symbols), self.compare_range
        if not symbols:
            self.compare_fig.clear()
            self.compare_canvas.draw_idle()
            for w in self.compare_table.winfo_children():
                w.destroy()
            label(self.compare_table, "Add a symbol above to start comparing.", "body", fg=FAINT).pack(pady=S(20))
            return
        self.compare_loader.show("Loading " + ", ".join(symbols) + "…")

        def work():
            def one(sym):
                return sym, fetch_history(sym, rk), fetch_info(sym)
            with ThreadPoolExecutor(max_workers=5) as pool:
                return list(pool.map(one, symbols))
        self.app.worker.run(work, lambda res: rid == self.compare_id and self._compare_show(res),
                            lambda e: (self.compare_loader.hide(), self.app.set_status("Couldn't load comparison data.")))

    def _compare_show(self, results):
        self.compare_loader.hide()
        closes = {sym: hist["Close"].tz_localize(None) if hist.index.tz is not None else hist["Close"]
                  for sym, hist, _ in results if not hist.empty}
        self.compare_data = {sym: info for sym, _, info in results}
        if not closes:
            return
        df = pd.DataFrame(closes)
        df.index = df.index.normalize()
        df = df.groupby(level=0).last().ffill().dropna()
        fig = self.compare_fig
        fig.clear()
        ax = fig.add_subplot(111)
        style_axes(ax, price_on_right=True)
        x = np.arange(len(df))
        changes = {}
        for i, sym in enumerate(self.compare_symbols):
            if sym not in df:
                continue
            series = (df[sym] / df[sym].iloc[0] - 1) * 100
            changes[sym] = series.iloc[-1]
            ax.plot(x, series.to_numpy(), color=self.COMPARE_COLORS[i], linewidth=1.8,
                    label=f"{sym}  {series.iloc[-1]:+.1f}%")
        ax.axhline(0, color=FAINT, linewidth=0.8, linestyle=(0, (2, 3)))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:+.0f}%"))
        ax.set_xlim(0, max(len(x) - 1, 1))
        set_index_ticks(ax, df.index, self.compare_range)
        ax.legend(loc="lower left", bbox_to_anchor=(0, 1.0), frameon=False, fontsize=8.5, ncol=5,
                  labelcolor=MUTED, borderaxespad=0.2)
        fig.subplots_adjust(left=0.02, right=0.93, top=0.88, bottom=0.1)
        self.compare_canvas.draw_idle()
        self._compare_table(changes)

    def _compare_table(self, changes):
        t = self.compare_table
        for w in t.winfo_children():
            w.destroy()
        specs = {spec["name"]: spec for _, metrics in FUNDAMENTALS for spec in metrics}
        t.columnconfigure(0, minsize=S(170))
        for c in range(1, len(self.compare_symbols) + 1):
            t.columnconfigure(c, weight=1, uniform="cmp")
        for c, sym in enumerate(self.compare_symbols, start=1):
            head = tk.Frame(t, bg=SURFACE)
            head.grid(row=0, column=c, sticky="e", pady=(S(6), S(8)), padx=S(8))
            dot = tk.Canvas(head, width=S(9), height=S(9), bg=SURFACE, highlightthickness=0)
            dot.create_oval(1, 1, S(8), S(8), fill=self.COMPARE_COLORS[c - 1], outline="")
            dot.pack(side="left", padx=(0, S(6)))
            name = label(head, sym, "body_semi", cursor="hand2")
            name.pack(side="left")
            name.bind("<Button-1>", lambda e, s=sym: self.load(s))
        for r, (row_name, spec_name) in enumerate(self.COMPARE_ROWS, start=1):
            tk.Frame(t, bg=BORDER, height=1).grid(row=2 * r - 1, column=0, columnspan=6, sticky="ew")
            label(t, row_name, "small", fg=MUTED).grid(row=2 * r, column=0, sticky="w", pady=S(6), padx=S(8))
            for c, sym in enumerate(self.compare_symbols, start=1):
                info = self.compare_data.get(sym, {})
                cell = self._compare_cell(t, row_name, specs.get(spec_name), info, changes.get(sym))
                cell.grid(row=2 * r, column=c, sticky="e", padx=S(8))

    def _compare_cell(self, parent, row_name, spec, info, change):
        if spec is not None:
            rating, text = judge_metric(spec, info)
            return rating_pill(parent, rating, text, width=9)
        price = info.get("regularMarketPrice") or info.get("currentPrice")
        prev = info.get("regularMarketPreviousClose")
        if row_name == "Price":
            return label(parent, fmt_price(price), "small_semi")
        if row_name == "Today":
            pct = (price / prev - 1) * 100 if price and prev else None
            return label(parent, fmt_pct(pct), "small_semi", fg=trend_color(pct))
        if row_name == "Period change":
            return label(parent, fmt_pct(change), "small_semi", fg=trend_color(change))
        if row_name == "Market cap":
            return label(parent, fmt_big(info.get("marketCap")), "small")
        if row_name == "Dividend yield":
            div = info.get("trailingAnnualDividendYield")
            return label(parent, f"{div * 100:.2f}%" if div else "—", "small")
        if row_name == "Beta":
            return label(parent, fmt_price(info.get("beta")), "small")
        if info.get("quoteType") != "EQUITY":
            return label(parent, "n/a", "small", fg=FAINT)
        ratings = [judge_metric(sp, info)[0] for _, metrics in FUNDAMENTALS for sp in metrics]
        box = tk.Frame(parent, bg=SURFACE)
        for rating in ("good", "fair", "weak"):
            rating_pill(box, rating, str(ratings.count(rating)), width=3).pack(side="left", padx=(S(3), 0))
        return box

    def _screenshot_compare(self):
        caption = chart_caption("Compare: " + " vs ".join(self.compare_symbols), f"% change, {self.compare_range}")
        save_screenshot(self.app, figure_image(self.compare_fig), "Compare " + " ".join(self.compare_symbols), caption)

    def first_load(self):
        self._load_overview()

    def refresh(self):
        if self.mode == "overview":
            self._load_overview()

    def reload(self):
        """F5: fresh data for whatever is on screen."""
        if self.mode == "detail" and self.data:
            forget_symbol(self.data["symbol"])
            self.load(self.data["symbol"])
        elif self.mode == "compare":
            for sym in self.compare_symbols:
                forget_symbol(sym)
            self._compare_load()
        else:
            self._load_overview()

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
        if not self.loaded:
            self.loaded = True
            self._load_overview()
        self._set_mode("detail")
        self.request_id += 1
        rid, rk = self.request_id, self.range_key
        self.scroller.to_top()
        self.loader.show(f"Loading {query.upper()}…")
        self.app.set_status(f"Loading {query.upper()}…")
        show_skeleton(self.news_box, blocks=2, lines=2)
        show_skeleton(self.stats_box, blocks=1, lines=8, pady=6)
        self.app.worker.run(lambda: load_symbol(query, rk),
                            lambda d: self._show(rid, d), lambda e: self._failed(rid, e))

    def set_range(self, range_key):
        self.range_key = range_key
        self.range_chips.set(range_key)
        if not self.data:
            return
        self.request_id += 1
        rid, sym = self.request_id, self.data["symbol"]
        slow = self.after(250, lambda: rid == self.request_id and self.loader.show("Loading…"))
        self.app.worker.run(lambda: fetch_history(sym, range_key),
                            lambda h: (self.after_cancel(slow), self._show_range(rid, h)),
                            lambda e: (self.after_cancel(slow), self._failed(rid, e)))

    def _render_recent(self):
        for w in self.recent_row.winfo_children():
            w.destroy()
        recent = self.app.settings.get("recent", [])[:6]
        if not recent:
            return
        label(self.recent_row, "RECENT", "eyebrow", fg=FAINT).pack(side="left", padx=(0, S(12)))
        for sym in recent:
            chip = RoundButton(self.recent_row, sym, lambda s=sym: self.load(s), kind="ghost", font="chip",
                               padx=10, pady=4, radius=12)
            chip.pack(side="left", padx=(0, S(6)))

    def _remember(self, symbol):
        recent = [symbol] + [s for s in self.app.settings.get("recent", []) if s != symbol]
        self.app.settings["recent"] = recent[:6]
        self._render_recent()

    def step_range(self, step):
        keys = list(RANGES)
        target = keys[(keys.index(self.range_key) + step) % len(keys)]
        self.set_range(target)

    def screenshot(self):
        if self.mode == "detail":
            self.save_chart()
        elif self.mode == "compare":
            self._screenshot_compare()
        else:
            self._screenshot_indices()

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
        if not self.data or not self.hover_artists:
            return
        self._hide_hover()
        sym = self.data["symbol"]
        name = self.data["info"].get("shortName") or sym
        caption = chart_caption(f"{name} ({sym})", self.price_label.cget("text"), self.period_label.cget("text"))
        save_screenshot(self.app, figure_image(self.fig), f"{sym} {self.range_key} chart", caption)

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

        self._update_watch_button()
        self._update_alert_note()
        self._draw_chart()
        self.canvas.draw()   # paint the chart now; the panels below are built a moment later
        self.app.set_status(f"Showing {sym}")
        self._remember(sym)
        self.app.update_title(sym)
        self.after(1, lambda: rid == self.request_id and self._fill_panels(sym, info))

    def _fill_panels(self, sym, info):
        """Statistics, fundamentals, profile and news — everything under and beside the chart."""
        self._fill_stats(info)
        about = info.get("longBusinessSummary") or ""
        self.about_title.configure(text=f"About {info.get('shortName') or sym}" if about else "")
        self.about_label.configure(text=(about[:520].rsplit(" ", 1)[0] + "…") if len(about) > 520 else about)
        self._fill_fundamentals(info)
        self._fill_news(sym, info)

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

    def _fill_news(self, symbol, info):
        """Headlines that mention this company, taken from the followed news outlets."""
        for w in self.news_box.winfo_children():
            w.destroy()
        name = info.get("shortName") or info.get("longName") or ""
        if info.get("quoteType") not in ("EQUITY", "ETF"):
            name = name if info.get("quoteType") != "CRYPTOCURRENCY" else name.split(" ")[0]
        matches = company_pattern(symbol, name)
        show_skeleton(self.news_box, blocks=2, lines=2)

        def show(news):
            if not self.data or self.data["symbol"] != symbol:
                return
            for w in self.news_box.winfo_children():
                w.destroy()
            found = [a for a in newest_first(news)
                     if matches(a["title"] + " " + a["summary"])
                     and FINANCE_PATTERN.search(a["title"] + " " + a["summary"])][:6]
            if not found:
                label(self.news_box, f"None of the {len(NEWS_SOURCES)} followed outlets have finance stories "
                                     f"about {name or symbol} in their latest headlines.", "body",
                      fg=FAINT).pack(anchor="w")
            for art in found:
                HeadlineRow(self.news_box, self.app, art).pack(fill="x")

        self.app.news.get(show, lambda e: None)

    # --- chart ------------------------------------------------------------------
    def _chart_message(self, text):
        self.loader.hide()
        self.fig.clear()
        self.hover_artists = None
        self.fig.text(0.5, 0.5, text, ha="center", va="center", color=FAINT, fontsize=11)
        self.canvas.draw_idle()

    def _draw_chart(self):
        self.loader.hide()
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
        set_index_ticks(axv or ax, hist.index, self.range_key)
        if axv is not None:
            style_axes(axv, price_on_right=True)
            ax.tick_params(labelbottom=False)
            volume = hist["Volume"].fillna(0).to_numpy()
            if len(x) > 160:    # one shape for many bars — drawing 1,000+ rectangles is slow
                axv.fill_between(x, volume, step="mid", color=BORDER, linewidth=0)
            else:
                axv.bar(x, volume, color=BORDER, width=0.8)
            axv.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: fmt_big(v) if v else ""))
            axv.yaxis.set_major_locator(MaxNLocator(2))
            axv.grid(False)

        word = RANGE_WORDS[self.range_key]
        self.period_label.configure(text=f"{fmt_pct(period_change)} {word}", fg=trend_color(period_change))

        # hover crosshair + readout
        vline = ax.axvline(0, color=MUTED, linewidth=0.8, linestyle=":", visible=False, animated=True)
        dot, = ax.plot([], [], "o", color=color, markersize=5, markeredgecolor=BG, markeredgewidth=1.5,
                       animated=True)
        tip = ax.text(0.99, 0.98, "", transform=ax.transAxes, ha="right", va="top", fontsize=8.5,
                      color=INK, bbox=dict(boxstyle="round,pad=0.5", fc=SURFACE, ec=BORDER), visible=False,
                      animated=True)
        self.hover_bg = None
        self.hover_artists = (ax, axv, vline, dot, tip, close, base, intraday)
        self.fig.subplots_adjust(left=0.02, right=0.92, top=0.97, bottom=0.08)
        self.canvas.draw_idle()

    def _save_background(self, _event):
        """After each full redraw, remember the chart image so hovering only redraws the crosshair."""
        if self.hover_artists:
            self.hover_bg = self.canvas.copy_from_bbox(self.fig.bbox)

    def _blit_hover(self, visible):
        if not self.hover_artists or self.hover_bg is None:
            return
        ax, axv, vline, dot, tip = self.hover_artists[:5]
        self.canvas.restore_region(self.hover_bg)
        for artist in (vline, dot, tip):
            artist.set_visible(visible)
            if visible:
                ax.draw_artist(artist)
        self.canvas.blit(self.fig.bbox)

    def _on_hover(self, event):
        if not self.hover_artists or not self.data:
            return
        ax, axv, vline, dot, tip, close, base, intraday = self.hover_artists
        if event.inaxes not in (ax, axv) or event.xdata is None:
            self._hide_hover()
            return
        i = int(min(max(round(event.xdata), 0), len(close) - 1))
        if getattr(self, "_hover_index", None) == i and vline.get_visible():
            return
        self._hover_index = i
        when = self.data["hist"].index[i]
        stamp = when.strftime("%a %b %d, %I:%M %p" if intraday else "%a %b %d, %Y").replace(" 0", " ")
        vol = self.data["hist"]["Volume"].iloc[i]
        tip.set_text(f"{stamp}\n{fmt_price(close[i])}   {fmt_pct((close[i] / base - 1) * 100)}"
                     + (f"\nVol {fmt_big(vol)}" if vol else ""))
        vline.set_xdata([i, i])
        dot.set_data([i], [close[i]])
        self._blit_hover(True)

    def _hide_hover(self):
        if self.hover_artists and self.hover_artists[2].get_visible():
            self._hover_index = None
            self._blit_hover(False)


class NewsPage(Page):
    refresh_ms = 10 * 60_000
    PAGE_SIZE = 30

    def build(self):
        self.topic, self.query, self.limit = "All", "", self.PAGE_SIZE
        self.articles = []
        self._filter_job = None
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        wrap = tk.Frame(self.scroller.inner, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(0, S(40)))

        head = self.page_header(wrap, "News", f"Headlines from {len(NEWS_SOURCES)} outlets across the political "
                                              "spectrum. Click a headline to read it on the publisher's site, "
                                              "or an outlet to learn about it.")
        search = tk.Frame(head, bg=BG)
        search.pack(side="right", anchor="s")
        self.search = SearchEntry(search, "Filter headlines e.g. inflation", self._apply_search, width=28)
        self.search.pack(side="left")
        self.search.entry.bind("<KeyRelease>", lambda e: self._schedule_filter(), add="+")

        self.topics = ChipGroup(wrap, list(NEWS_TOPICS), self.set_topic, value="All")
        self.topics.pack(anchor="w", pady=(0, S(20)))

        cols = tk.Frame(wrap, bg=BG)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=3, uniform="news")
        cols.columnconfigure(1, weight=2, uniform="news")

        left = tk.Frame(cols, bg=BG)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, S(24)))
        top = tk.Frame(left, bg=BG)
        top.pack(fill="x")
        self.list_title = label(top, "Latest Headlines", "h2")
        self.list_title.pack(side="left")
        self.count_label = label(top, "", "small", fg=FAINT)
        self.count_label.pack(side="right", anchor="s")
        divider(left, pady=(S(10), 0))
        self.list = tk.Frame(left, bg=BG)
        self.list.pack(fill="x")
        show_skeleton(self.list, blocks=6, lines=3, pady=22)
        self.more = RoundButton(left, "Show more headlines", self._show_more, kind="ghost")

        right = tk.Frame(cols, bg=BG)
        right.grid(row=0, column=1, sticky="nsew", padx=(S(8), 0))
        sources = card(right)
        sources.pack(fill="x")
        sbox = tk.Frame(sources, bg=SURFACE)
        sbox.pack(fill="both", expand=True, padx=S(22), pady=S(18))
        label(sbox, "Browse by Source", "h2").pack(anchor="w")
        label(sbox, "Ordered from left to right by AllSides Media Bias Rating", "small",
              fg=MUTED).pack(anchor="w", pady=(0, S(8)))
        self.source_counts = {}
        for src in sorted(NEWS_SOURCES, key=lambda s: (BIAS_SCALE.index(s["bias"]), s["name"])):
            divider(sbox)
            row = tk.Frame(sbox, bg=SURFACE)
            row.pack(fill="x")
            source_badge(row, src).pack(side="left", pady=S(8), padx=(S(4), S(10)))
            label(row, src["name"], "body").pack(side="left")
            BiasScale(row, src["bias"], width=70, compact=True).pack(side="right", padx=(S(10), S(4)))
            count = label(row, "", "small", fg=FAINT)
            count.pack(side="right")
            self.source_counts[src["id"]] = count
            make_clickable(row, lambda i=src["id"]: self.app.show_source(i))
            add_hover(row, lambda r=row: set_bg(r, SAND), lambda r=row: set_bg(r, SURFACE))
        link = label(sbox, "About AllSides ratings →", "small_semi", fg=ACCENT)
        link.pack(anchor="w", pady=(S(12), 0))
        make_clickable(link, lambda: open_link("https://www.allsides.com/media-bias/media-bias-rating-methods"))

        milton = tk.Frame(right, bg=SAND)
        milton.pack(fill="x", pady=(S(20), 0))
        mbox = tk.Frame(milton, bg=SAND)
        mbox.pack(fill="both", expand=True, padx=S(22), pady=S(18))
        mtop = tk.Frame(mbox, bg=SAND)
        mtop.pack(fill="x")
        label(mtop, "From The Milton Review", "h2").pack(side="left")
        more = label(mtop, "Visit blog →", "small_semi", fg=ACCENT)
        more.pack(side="right")
        make_clickable(more, lambda: open_link(BLOG_URL))
        self.milton_list = tk.Frame(mbox, bg=SAND)
        self.milton_list.pack(fill="x", pady=(S(8), 0))

    # --- data -----------------------------------------------------------------------
    def first_load(self):
        self.app.news.get(self._got_news, self._news_failed)
        self.app.milton.get(self._show_milton, lambda e: None)

    def refresh(self):
        self.app.news.get(self._got_news, self._news_failed, force=True)

    def _got_news(self, news):
        self.articles = newest_first(news)
        for sid, count in self.source_counts.items():
            n = len(news.get(sid, []))
            count.configure(text=f"{n} stories" if n else "offline")
        self._render()

    def _news_failed(self, error):
        for w in self.list.winfo_children():
            w.destroy()
        label(self.list, "Couldn't load the news. Check your connection.", "body",
              fg=DOWN).pack(anchor="w", pady=S(12))

    def _show_milton(self, articles):
        for w in self.milton_list.winfo_children():
            w.destroy()
        for art in articles[:6]:
            row = tk.Frame(self.milton_list, bg=SAND)
            row.pack(fill="x", pady=S(6))
            label(row, f"{art['author']}  ·  {short_date(art['date'])}", "small", fg=FAINT).pack(anchor="w")
            wrap_label(row, art["title"], "card_title").pack(fill="x")
            make_clickable(row, lambda url=art["link"]: open_link(url))

    # --- filtering (all local, so it's instant) -------------------------------------
    def set_topic(self, topic):
        self.topic, self.limit = topic or "All", self.PAGE_SIZE
        self._render()

    def _schedule_filter(self):
        if self._filter_job:
            self.after_cancel(self._filter_job)
        self._filter_job = self.after(250, self._apply_search)

    def _apply_search(self):
        self._filter_job = None
        query = self.search.get().lower()
        if query != self.query:
            self.query, self.limit = query, self.PAGE_SIZE
            self._render()

    def _show_more(self):
        self.limit += self.PAGE_SIZE
        self._render(keep_scroll=True)

    def _filtered(self):
        pattern = TOPIC_PATTERNS.get(self.topic)
        words = self.query.split()
        out = []
        for art in self.articles:
            text = f"{art['title']} {art['summary']}"
            if pattern and not pattern.search(text):
                continue
            low = text.lower()
            if words and not all(w in low for w in words):
                continue
            out.append(art)
        return out

    def _render(self, keep_scroll=False):
        if not self.articles:
            return
        items = self._filtered()
        for w in self.list.winfo_children():
            w.destroy()
        title = "Latest Headlines" if self.topic == "All" else self.topic
        self.list_title.configure(text=f"Results for “{self.query}”" if self.query else title)
        shown = items[:self.limit]
        self.count_label.configure(text=f"Showing {len(shown)} of {len(items)}")
        if not items:
            label(self.list, "No headlines match right now.", "body", fg=FAINT).pack(anchor="w", pady=S(12))
        for art in shown:
            HeadlineRow(self.list, self.app, art).pack(fill="x")
        if len(items) > self.limit:
            self.more.pack(anchor="w", pady=(S(16), 0))
        else:
            self.more.pack_forget()
        if not keep_scroll:
            self.scroller.to_top()


class SourcePage(Page):
    """About one news outlet: summary, political alignment and its top stories."""
    refresh_ms = None

    def build(self):
        self.source = None
        self.request_id = 0
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        wrap = tk.Frame(self.scroller.inner, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(S(28), S(40)))
        back = label(wrap, "← All news", "body_semi", fg=ACCENT)
        back.pack(anchor="w")
        make_clickable(back, lambda: self.app.navigate("News"))
        self.content = tk.Frame(wrap, bg=BG)
        self.content.pack(fill="both", expand=True)

    def open(self, source_id):
        src = SOURCES_BY_ID[source_id]
        self.source = src
        self.app.update_title()
        self.request_id += 1
        for w in self.content.winfo_children():
            w.destroy()
        self.scroller.to_top()

        head = tk.Frame(self.content, bg=BG)
        head.pack(fill="x", pady=(S(18), S(22)))
        source_badge(head, src, font="h2", padx=14, pady=8, width=0).pack(side="left", anchor="n",
                                                                         padx=(0, S(18)))
        names = tk.Frame(head, bg=BG)
        names.pack(side="left", anchor="w")
        label(names, src["name"], "page_title").pack(anchor="w")
        site = label(names, src["site"].replace("https://", "").replace("www.", "") + "  ↗", "body_semi",
                     fg=ACCENT)
        site.pack(anchor="w")
        make_clickable(site, lambda: open_link(src["site"]))

        cols = tk.Frame(self.content, bg=BG)
        cols.pack(fill="x")
        cols.columnconfigure(0, weight=3, uniform="src")
        cols.columnconfigure(1, weight=2, uniform="src")

        about = tk.Frame(cols, bg=BG)
        about.grid(row=0, column=0, sticky="nsew", padx=(0, S(28)))
        label(about, "ABOUT", "eyebrow", fg=ACCENT).pack(anchor="w")
        wrap_label(about, src["about"], "lead").pack(fill="x", pady=(S(6), S(16)))
        facts = tk.Frame(about, bg=BG)
        facts.pack(fill="x")
        for key, value in src["facts"].items():
            divider(facts)
            row = tk.Frame(facts, bg=BG)
            row.pack(fill="x", pady=S(7))
            label(row, key, "small", fg=MUTED, width=16, anchor="w").pack(side="left")
            label(row, value, "small_semi").pack(side="left")
        divider(facts)

        bias = card(cols)
        bias.grid(row=0, column=1, sticky="nsew")
        bbox = tk.Frame(bias, bg=SURFACE)
        bbox.pack(fill="both", expand=True, padx=S(24), pady=S(20))
        label(bbox, "POLITICAL ALIGNMENT", "eyebrow", fg=ACCENT).pack(anchor="w")
        label(bbox, src["bias"], "h2", fg=bias_text_color(src["bias"])).pack(anchor="w", pady=(S(4), S(8)))
        BiasScale(bbox, src["bias"]).pack(fill="x")
        wrap_label(bbox, BIAS_MEANING[src["bias"]], "small", fg=MUTED).pack(fill="x", pady=(S(8), S(10)))
        wrap_label(bbox, "Rating: AllSides Media Bias Rating™, based on blind surveys of readers across the "
                         "spectrum, editorial reviews and independent research. It describes the outlet's "
                         "online news coverage, not individual articles.", "small",
                   fg=FAINT).pack(fill="x")
        link = label(bbox, f"See {src['short'] if len(src['name']) > 16 else src['name']} on AllSides →",
                     "small_semi", fg=ACCENT)
        link.pack(anchor="w", pady=(S(10), 0))
        make_clickable(link, lambda: open_link(src["allsides"]))

        section_header(self.content, "Top Stories", f"In the order {src['name']} features them")
        self.stories = tk.Frame(self.content, bg=BG)
        self.stories.pack(fill="x")
        show_skeleton(self.stories, blocks=3, lines=3)
        rid = self.request_id
        self.app.news.get(lambda news: self._show_stories(rid, news.get(src["id"], [])),
                          lambda e: self._show_stories(rid, []))

    def _show_stories(self, rid, articles):
        if rid != self.request_id:
            return
        for w in self.stories.winfo_children():
            w.destroy()
        if not articles:
            label(self.stories, f"Couldn't load stories from {self.source['name']} right now.", "body",
                  fg=DOWN).pack(anchor="w")
            return
        top = sorted(articles, key=lambda a: a["rank"])[:9]
        thumbs = []
        for i, art in enumerate(top):
            row, col = divmod(i, 3)
            self.stories.columnconfigure(col, weight=1, uniform="story")
            c = card(self.stories)
            c.grid(row=row, column=col, sticky="nsew", pady=S(8),
                   padx=(0 if col == 0 else S(8), 0 if col == 2 else S(8)))
            thumb = Thumbnail(c, 170, placeholder=self.source["short"])
            if art["image"]:
                thumb.pack(fill="x")
                thumbs.append((thumb, art["image"]))
            box = tk.Frame(c, bg=SURFACE)
            box.pack(fill="both", expand=True, padx=S(18), pady=S(14))
            label(box, time_ago(art["date"]) if art["date"] else "", "small", fg=FAINT).pack(anchor="w")
            wrap_label(box, art["title"], "card_title").pack(fill="x", pady=(S(2), S(4)))
            if art["summary"]:
                text = art["summary"]
                text = text[:150].rsplit(" ", 1)[0] + "…" if len(text) > 150 else text
                wrap_label(box, text, "small", fg=MUTED).pack(fill="x")
            label(box, "Read on " + self.source["name"] + " →", "small_semi", fg=ACCENT).pack(anchor="w", pady=(S(8), 0))
            make_clickable(c, lambda url=art["link"]: open_link(url))
            hover_border(c)
        if thumbs:
            self.app.worker.run(lambda: fetch_images([u for _, u in thumbs]),
                                lambda imgs: rid == self.request_id and
                                [t.set_image(im) for (t, _), im in zip(thumbs, imgs) if im])


# ------------------------------------------------------------ Watchlist ------
class WatchlistPage(Page):
    refresh_ms = 60_000
    # header, min width, stretch, alignment
    COLUMNS = [("SYMBOL", 96, 0, "w"), ("NAME", 200, 1, "w"), ("LAST", 104, 0, "e"),
               ("CHANGE", 96, 0, "e"), ("% CHANGE", 104, 0, "e"), ("DAY RANGE", 180, 0, "e"),
               ("VOLUME", 100, 0, "e"), ("1 MONTH", 150, 0, "e"), ("", 44, 0, "e")]

    # column index -> sort value (rows without prices always go last)
    SORTS = {0: lambda item, q: item["symbol"], 1: lambda item, q: (item.get("name") or "").lower(),
             2: lambda item, q: q["last"], 3: lambda item, q: q["change"], 4: lambda item, q: q["pct"],
             6: lambda item, q: q["volume"]}

    def build(self):
        self.quotes = {}
        self.sort = None   # (column, descending) or None for your own order
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        wrap = tk.Frame(self.scroller.inner, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(0, S(40)))

        head = self.page_header(wrap, "Watchlist", "Your saved symbols, refreshed every minute. "
                                                   "Click a row to open its chart, or a column to sort.")
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

        alerts_head = tk.Frame(wrap, bg=BG)
        alerts_head.pack(fill="x", pady=(S(32), S(10)))
        label(alerts_head, "Price Alerts", "h2").pack(side="left")
        clear = label(alerts_head, "Clear triggered", "small_semi", fg=ACCENT, cursor="hand2")
        clear.pack(side="right")
        clear.bind("<Button-1>", lambda e: self.app.alerts.clear_triggered())
        label(wrap, "Set alerts from any stock's page (“Set price alert”). You'll get a Windows notification "
                    "while the app is open, even minimized.", "small", fg=MUTED).pack(anchor="w", pady=(0, S(10)))
        alerts = card(wrap)
        alerts.pack(fill="x")
        self.alert_box = tk.Frame(alerts, bg=SURFACE)
        self.alert_box.pack(fill="x", padx=S(14), pady=S(8))
        self.app.alerts.listeners.append(self._render_alerts)
        self._render_alerts()

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
            arrow = ""
            if self.sort and self.sort[0] == i:
                arrow = "  ▼" if self.sort[1] else "  ▲"
            head = label(header, title + arrow, "eyebrow", fg=INK if arrow else FAINT)
            head.grid(row=0, column=i, sticky=anchor, padx=S(10), pady=(S(10), S(8)))
            if i in self.SORTS:
                head.configure(cursor="hand2")
                head.bind("<Button-1>", lambda e, c=i: self._sort_by(c))
        items = self._sorted(self.app.watchlist.items)
        if not items:
            divider(self.table)
            label(self.table, "Your watchlist is empty. Add a symbol above, or use “Add to Watchlist” "
                              "on the Markets page.", "body", fg=MUTED).pack(pady=S(36))
            return
        for item in items:
            divider(self.table)
            self._row(item)

    def _render_alerts(self):
        box = self.alert_box
        for w in box.winfo_children():
            w.destroy()
        items = sorted(self.app.alerts.items, key=lambda a: (a["triggered"] is not None, a["symbol"]))
        if not items:
            label(box, "No price alerts yet.", "body", fg=FAINT).pack(anchor="w", pady=S(14), padx=S(6))
            return
        for i, a in enumerate(items):
            if i:
                divider(box)
            row = tk.Frame(box, bg=SURFACE)
            row.pack(fill="x")
            sym = label(row, a["symbol"], "body_semi", width=8, anchor="w", cursor="hand2")
            sym.pack(side="left", padx=(S(6), 0), pady=S(10))
            sym.bind("<Button-1>", lambda e, s=a["symbol"]: self.app.open_symbol(s))
            label(row, describe_alert(a), "body").pack(side="left")
            remove = label(row, "✕", "body", fg=FAINT, cursor="hand2")
            remove.pack(side="right", padx=S(8))
            remove.bind("<Button-1>", lambda e, k=a["id"]: self.app.alerts.remove(k))
            if a["triggered"]:
                when = datetime.fromisoformat(a["triggered"])
                text = f"Triggered {short_date(when)} {clock_time(when)} at {fmt_price(a['price'])}"
                rating_pill(row, "good", text, width=0).pack(side="right", padx=S(10))
            else:
                rating_pill(row, None, "Watching", width=0).pack(side="right", padx=S(10))

    def _sort_by(self, column):
        """Click once for ascending, again for descending, a third time for your own order."""
        if not self.sort or self.sort[0] != column:
            self.sort = (column, column in (2, 3, 4, 6))   # numbers start biggest-first
        elif self.sort[1] == (column in (2, 3, 4, 6)):
            self.sort = (column, not self.sort[1])
        else:
            self.sort = None
        self.render()

    def _sorted(self, items):
        if not self.sort:
            return items
        column, descending = self.sort
        key = self.SORTS[column]
        priced = [i for i in items if column < 2 or i["symbol"] in self.quotes]
        rest = [i for i in items if i not in priced]
        priced.sort(key=lambda i: key(i, self.quotes.get(i["symbol"])), reverse=descending)
        return priced + rest

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
        row.bind("<Enter>", lambda e: prefetch(sym, self.app.pages["Markets"].range_key), add="+")
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
        curve_head = tk.Frame(left, bg=BG)
        curve_head.pack(fill="x")
        label(curve_head, "The Yield Curve", "h2").pack(side="left")
        CameraButton(curve_head, self._screenshot_curve).pack(side="right")
        label(left, "Today compared with one month and one year ago", "small", fg=MUTED).pack(anchor="w")
        self.curve_fig = Figure(figsize=(8, 3.8), dpi=96 * SCALE, facecolor=BG)
        self.curve_canvas = FigureCanvasTkAgg(self.curve_fig, master=left)
        w = self.curve_canvas.get_tk_widget()
        w.configure(height=S(380), bg=BG, highlightthickness=0)
        w.pack(fill="x", pady=(S(8), 0))
        self.curve_loader = ChartLoader(w)

        table = card(row)
        table.grid(row=0, column=1, sticky="new")
        tbox = tk.Frame(table, bg=SURFACE)
        tbox.pack(fill="both", expand=True, padx=S(22), pady=S(18))
        label(tbox, "Yields by Maturity", "h2").pack(anchor="w", pady=(0, S(8)))
        self.table = tk.Frame(tbox, bg=SURFACE)
        self.table.pack(fill="x")

        # spread history
        spread_head = tk.Frame(wrap, bg=BG)
        spread_head.pack(fill="x", pady=(S(36), 0))
        label(spread_head, "Recession Watch", "h2").pack(side="left")
        CameraButton(spread_head, self._screenshot_spreads).pack(side="right")
        label(wrap, "Spread between long and short Treasury yields over the past two years. "
                    "Below zero means the curve is inverted.", "small", fg=MUTED).pack(anchor="w")
        self.spread_fig = Figure(figsize=(10, 3), dpi=96 * SCALE, facecolor=BG)
        self.spread_canvas = FigureCanvasTkAgg(self.spread_fig, master=wrap)
        w = self.spread_canvas.get_tk_widget()
        w.configure(height=S(300), bg=BG, highlightthickness=0)
        w.pack(fill="x", pady=(S(8), 0))
        self.spread_loader = ChartLoader(w)

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

    def _screenshot_curve(self):
        caption = "U.S. Treasury par yield curve  ·  " + self.asof.cget("text").split("  ·  ")[0]
        save_screenshot(self.app, figure_image(self.curve_fig), "Treasury yield curve", caption)

    def screenshot(self):
        self._screenshot_curve()

    def _screenshot_spreads(self):
        caption = chart_caption("Treasury spreads: 10Y – 2Y and 10Y – 3M", "Source: U.S. Treasury")
        save_screenshot(self.app, figure_image(self.spread_fig), "Treasury spread history", caption)

    def first_load(self):
        self.refresh()

    def refresh(self):
        self.curve_loader.show("Loading Treasury yields…")
        self.spread_loader.show("Loading spread history…")
        self.app.worker.run(fetch_treasury, self._show, self._failed)

    def _failed(self, error):
        self.curve_loader.hide()
        self.spread_loader.hide()
        self.asof.configure(text=str(error), fg=DOWN)
        self._message(self.curve_fig, self.curve_canvas, "Treasury data unavailable")
        self._message(self.spread_fig, self.spread_canvas, "")

    @staticmethod
    def _message(fig, canvas, text):
        fig.clear()
        fig.text(0.5, 0.5, text, ha="center", va="center", color=FAINT, fontsize=11)
        canvas.draw_idle()

    def _show(self, df):
        self.curve_loader.hide()
        self.spread_loader.hide()
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


# ------------------------------------------------------------- Portfolio ------
PIE_COLORS = ["#D47A5D", "#5B7FA6", "#7E9B6A", "#C9A227", "#8E79AE", "#4E9A9A", "#B5654A", "#9AA0A6"]


class PortfolioPage(Page):
    refresh_ms = 60_000
    PERF_RANGES = ["1M", "6M", "YTD", "1Y", "5Y"]
    COLUMNS = [("SYMBOL", 84, 0, "w"), ("NAME", 160, 1, "w"), ("SHARES", 76, 0, "e"), ("AVG COST", 90, 0, "e"),
               ("PRICE", 90, 0, "e"), ("VALUE", 110, 0, "e"), ("TODAY", 104, 0, "e"),
               ("TOTAL GAIN", 160, 0, "e"), ("WEIGHT", 70, 0, "e"), ("", 70, 0, "e")]

    def build(self):
        self.data, self.history, self.alloc_mode, self.perf_range = None, None, "Holdings", "1Y"
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        wrap = tk.Frame(self.scroller.inner, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(0, S(40)))
        head = self.page_header(wrap, "Portfolio", "Track what you own — value, gains, allocation and dividend "
                                                   "income. Prices refresh every minute.")
        RoundButton(head, "Refresh", self.refresh, kind="ghost").pack(side="right", anchor="s")
        RoundButton(head, "Export CSV", self.export_csv, kind="ghost").pack(side="right", anchor="s", padx=(0, S(10)))
        RoundButton(head, "Import CSV", self.import_csv).pack(side="right", anchor="s", padx=(0, S(10)))

        form = card(wrap)
        form.pack(fill="x")
        fbox = tk.Frame(form, bg=SURFACE)
        fbox.pack(fill="x", padx=S(22), pady=S(18))
        label(fbox, "ADD OR UPDATE A HOLDING", "eyebrow", fg=ACCENT).pack(anchor="w")
        row = tk.Frame(fbox, bg=SURFACE)
        row.pack(fill="x", pady=(S(10), 0))
        self.sym_entry = SearchEntry(row, "Symbol e.g. AAPL", self.save_holding, width=16)
        self.sym_entry.pack(side="left")
        self.shares_entry = SearchEntry(row, "Shares e.g. 10", self.save_holding, width=14)
        self.shares_entry.pack(side="left", padx=(S(10), 0))
        self.cost_entry = SearchEntry(row, "Average price paid per share e.g. 180", self.save_holding, width=32)
        self.cost_entry.pack(side="left", padx=(S(10), 0))
        RoundButton(row, "Save holding", self.save_holding).pack(side="left", padx=(S(10), 0))
        self.form_msg = label(fbox, "Tip: saving a symbol you already own updates it. Click ✎ on a row to edit. "
                                    "To add many at once, use Import CSV — or drag a CSV file onto this window.",
                              "small", fg=FAINT)
        self.form_msg.pack(anchor="w", pady=(S(10), 0))
        Suggester(self.app, self.sym_entry, lambda s: (self.sym_entry.set(s), self.shares_entry.focus()))

        self.empty = tk.Frame(wrap, bg=BG)
        label(self.empty, "Your portfolio is empty", "h2").pack(anchor="w", pady=(S(28), S(4)))
        label(self.empty, "Add your first holding above — for example AAPL, 10 shares at $180 — to see its value, "
                          "gains, allocation and dividends.", "body", fg=MUTED).pack(anchor="w")
        label(self.empty, "Already tracking it somewhere else? Download a positions CSV from your broker (or save "
                          "your spreadsheet as CSV) and press Import CSV, or drag the file onto this window.", "body",
              fg=MUTED).pack(anchor="w", pady=(S(6), 0))
        self.content = tk.Frame(wrap, bg=BG)

        cards = tk.Frame(self.content, bg=BG)
        cards.pack(fill="x", pady=(S(24), 0))
        self.summary = {}
        for i, key in enumerate(("Total value", "Today", "Total gain", "Yearly dividends")):
            cards.columnconfigure(i, weight=1, uniform="pf")
            c = card(cards)
            c.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else S(8), 0 if i == 3 else S(8)))
            box = tk.Frame(c, bg=SURFACE)
            box.pack(fill="both", expand=True, padx=S(20), pady=S(16))
            label(box, key.upper(), "eyebrow", fg=MUTED).pack(anchor="w")
            value = label(box, "—", "card_value")
            value.pack(anchor="w", pady=(S(6), S(2)))
            sub_label = label(box, " ", "small", fg=FAINT)
            sub_label.pack(anchor="w")
            self.summary[key] = (value, sub_label)

        label(self.content, "Holdings", "h2").pack(anchor="w", pady=(S(28), S(10)))
        table = card(self.content)
        table.pack(fill="x")
        self.table = tk.Frame(table, bg=SURFACE)
        self.table.pack(fill="x", padx=S(8), pady=S(6))

        charts = tk.Frame(self.content, bg=BG)
        charts.pack(fill="x", pady=(S(28), 0))
        charts.columnconfigure(0, weight=2, uniform="pfc")
        charts.columnconfigure(1, weight=3, uniform="pfc")
        left = card(charts)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, S(10)))
        lbox = tk.Frame(left, bg=SURFACE)
        lbox.pack(fill="both", expand=True, padx=S(20), pady=S(16))
        lhead = tk.Frame(lbox, bg=SURFACE)
        lhead.pack(fill="x")
        label(lhead, "Allocation", "h2").pack(side="left")
        CameraButton(lhead, self._screenshot_allocation).pack(side="right")
        ChipGroup(lhead, ["Holdings", "Sectors"], self._set_alloc, value="Holdings").pack(side="right", padx=S(10))
        self.alloc_fig = Figure(figsize=(5, 3.2), dpi=96 * SCALE, facecolor=SURFACE)
        self.alloc_canvas = FigureCanvasTkAgg(self.alloc_fig, master=lbox)
        w = self.alloc_canvas.get_tk_widget()
        w.configure(height=S(300), bg=SURFACE, highlightthickness=0)
        w.pack(fill="x", pady=(S(8), 0))

        right = card(charts)
        right.grid(row=0, column=1, sticky="nsew", padx=(S(10), 0))
        rbox = tk.Frame(right, bg=SURFACE)
        rbox.pack(fill="both", expand=True, padx=S(20), pady=S(16))
        rhead = tk.Frame(rbox, bg=SURFACE)
        rhead.pack(fill="x")
        label(rhead, "Performance vs S&P 500", "h2").pack(side="left")
        CameraButton(rhead, self._screenshot_performance).pack(side="right")
        ChipGroup(rhead, self.PERF_RANGES, self._set_perf_range, value=self.perf_range).pack(side="right", padx=S(10))
        label(rbox, "How today's holdings would have done over the period, compared with the S&P 500.", "small",
              fg=MUTED).pack(anchor="w")
        self.perf_fig = Figure(figsize=(7, 3.2), dpi=96 * SCALE, facecolor=SURFACE)
        self.perf_canvas = FigureCanvasTkAgg(self.perf_fig, master=rbox)
        w = self.perf_canvas.get_tk_widget()
        w.configure(height=S(280), bg=SURFACE, highlightthickness=0)
        w.pack(fill="x", pady=(S(8), 0))
        self.perf_loader = ChartLoader(w)

        label(self.content, "Dividend Income", "h2").pack(anchor="w", pady=(S(28), S(4)))
        label(self.content, "Estimated from each company's current yearly dividend rate. Dividends can change.",
              "small", fg=MUTED).pack(anchor="w", pady=(0, S(10)))
        div = card(self.content)
        div.pack(fill="x")
        self.div_box = tk.Frame(div, bg=SURFACE)
        self.div_box.pack(fill="x", padx=S(14), pady=S(8))
        self.app.portfolio.listeners.append(self._changed)

    # --- data -------------------------------------------------------------------------
    def first_load(self):
        self._toggle_empty()
        self.refresh()

    def _toggle_empty(self):
        if self.app.portfolio.items:
            self.empty.pack_forget()
            self.content.pack(fill="both", expand=True)
        else:
            self.content.pack_forget()
            self.empty.pack(fill="x")

    def _changed(self):
        if self.loaded:
            self._toggle_empty()
            self.refresh()

    def refresh(self):
        symbols = self.app.portfolio.symbols
        if not symbols:
            return
        if self.data is None:
            show_skeleton(self.table, blocks=2, lines=2)
        self.app.worker.run(lambda: fetch_portfolio(symbols), self._got,
                            lambda e: self.form_msg.configure(text="Couldn't refresh prices. Check your connection.",
                                                              fg=DOWN))
        self.perf_loader.show("Loading history…")
        self.app.worker.run(lambda: fetch_portfolio_history(tuple(symbols)), self._got_history,
                            lambda e: self.perf_loader.hide())

    def _got(self, data):
        self.data = data
        self._render()

    def _got_history(self, df):
        self.history = df
        self._draw_performance()

    def screenshot(self):
        self._screenshot_performance()

    # --- form --------------------------------------------------------------------------
    def save_holding(self):
        text = self.sym_entry.get()
        try:
            shares = float(self.shares_entry.get().replace(",", ""))
            cost = float(self.cost_entry.get().replace("$", "").replace(",", ""))
            assert shares > 0 and cost >= 0 and text
        except (ValueError, AssertionError):
            self.form_msg.configure(text="Enter a symbol, a number of shares and the average price you paid.", fg=DOWN)
            return
        self.form_msg.configure(text=f"Looking up {text.upper()}…", fg=FAINT)

        def resolve():
            sym = text.upper()
            quotes = fetch_quotes([sym]) if TICKER_RE.match(sym) else {}
            if sym not in quotes:
                sym = search_symbol(text)[0]
            info = fetch_info(sym)
            return sym, info.get("shortName") or info.get("longName") or ""

        def done(result):
            sym, name = result
            self.app.portfolio.set_holding(sym, name, shares, cost)
            for entry in (self.sym_entry, self.shares_entry, self.cost_entry):
                entry.clear()
            self.form_msg.configure(text=f"Saved {sym}: {shares:g} shares at {fmt_money(cost)}.", fg=UP)

        self.app.worker.run(resolve, done,
                            lambda e: self.form_msg.configure(text=f"Couldn't find “{text}”.", fg=DOWN))

    def import_csv(self, path=None):
        path = path or filedialog.askopenfilename(
            title="Import portfolio from CSV", filetypes=[("CSV files", "*.csv"), ("Text files", "*.txt"),
                                                          ("All files", "*.*")])
        if path:
            ImportDialog(self.app, path)

    def export_csv(self):
        items = self.app.portfolio.items
        if not items:
            self.form_msg.configure(text="Nothing to export yet — add a holding first.", fg=DOWN)
            return
        path = filedialog.asksaveasfilename(
            title="Export portfolio", defaultextension=".csv", filetypes=[("CSV file", "*.csv")],
            initialfile=f"Insight by Milton portfolio {datetime.now():%Y-%m-%d}.csv")
        if not path:
            return
        rows = self._rows() if self.data else [dict(h, price=None, value=None, day=None, gain=None, gain_pct=None)
                                                for h in items]
        total = sum(r["value"] for r in rows if r["value"]) or 0

        def num(v, places=2):
            return "" if v is None else f"{v:.{places}f}"
        try:
            with open(path, "w", newline="", encoding="utf-8") as f:
                out = csv.writer(f)
                out.writerow(["Symbol", "Name", "Shares", "Average Cost", "Price", "Market Value", "Today's Change",
                              "Total Gain", "Total Gain %", "Weight %"])
                for r in rows:
                    out.writerow([r["symbol"], r.get("name", ""), f"{r['shares']:g}", num(r.get("cost")),
                                  num(r["price"]), num(r["value"]), num(r["day"]), num(r["gain"]),
                                  num(r["gain_pct"]), num(r["value"] / total * 100 if r["value"] and total else None)])
            self.app.set_status(f"Portfolio exported: {os.path.basename(path)}")
        except OSError as exc:
            self.form_msg.configure(text=f"Couldn't save the file: {exc}", fg=DOWN)

    def _edit(self, holding):
        self.sym_entry.set(holding["symbol"])
        self.shares_entry.set(f"{holding['shares']:g}")
        if holding.get("cost") is not None:
            self.cost_entry.set(f"{holding['cost']:g}")
        else:
            self.cost_entry.clear()
        self.form_msg.configure(text=f"Editing {holding['symbol']} — change the numbers and press Save holding.",
                                fg=FAINT)
        self.scroller.to_top()

    # --- rendering -------------------------------------------------------------------
    def _rows(self):
        quotes, infos = self.data["quotes"], self.data["infos"]
        rows = []
        for h in self.app.portfolio.items:
            q, info = quotes.get(h["symbol"]), infos.get(h["symbol"], {})
            price = q["last"] if q else None
            value = price * h["shares"] if price else None
            rate = info.get("dividendRate") or info.get("trailingAnnualDividendRate") or 0
            kind = info.get("quoteType")
            cost = h.get("cost")      # None when imported without a cost basis
            rows.append({**h, "name": tidy_name(info.get("shortName")) or h.get("name", ""), "cost": cost, "price": price,
                         "value": value,
                         "day": q["change"] * h["shares"] if q else None,
                         "day_pct": q["pct"] if q else None,
                         "gain": value - h["shares"] * cost if value is not None and cost is not None else None,
                         "gain_pct": (price / cost - 1) * 100 if price and cost else None,
                         "dividend": rate, "income": rate * h["shares"],
                         "sector": "ETFs & funds" if kind in ("ETF", "MUTUALFUND") else
                                   "Crypto" if kind == "CRYPTOCURRENCY" else info.get("sector") or "Other"})
        return rows

    def _render(self):
        rows = self._rows()
        priced = [r for r in rows if r["value"] is not None]
        total = sum(r["value"] for r in priced)
        with_cost = [r for r in priced if r["cost"] is not None]
        cost = sum(r["shares"] * r["cost"] for r in with_cost)
        cost_value = sum(r["value"] for r in with_cost)
        day = sum(r["day"] for r in priced)
        income = sum(r["income"] for r in rows)
        start = total - day
        set_card = lambda key, value, sub, color=None: (self.summary[key][0].configure(text=value, fg=color or INK),
                                                         self.summary[key][1].configure(text=sub))
        set_card("Total value", fmt_money(total), f"{len(rows)} holding{'s' if len(rows) != 1 else ''} · "
                                                  f"cost {fmt_money(cost, decimals=0)}")
        set_card("Today", fmt_money(day, signed=True), fmt_pct(day / start * 100 if start else None), trend_color(day))
        missing = len(priced) - len(with_cost)
        set_card("Total gain", fmt_money(cost_value - cost, signed=True),
                 fmt_pct((cost_value / cost - 1) * 100 if cost else None)
                 + (f" · {missing} without cost" if missing else ""), trend_color(cost_value - cost))
        set_card("Yearly dividends", fmt_money(income), f"{income / total * 100:.2f}% yield on value" if total else " ")
        self._render_table(rows, total)
        self._draw_allocation(rows, total)
        self._render_dividends(rows, cost)

    def _render_table(self, rows, total):
        t = self.table
        for w in t.winfo_children():
            w.destroy()
        header = tk.Frame(t, bg=SURFACE)
        header.pack(fill="x")
        for i, (title, width, stretch, anchor) in enumerate(self.COLUMNS):
            header.columnconfigure(i, minsize=S(width), weight=stretch)
            label(header, title, "eyebrow", fg=FAINT).grid(row=0, column=i, sticky=anchor, padx=S(8), pady=(S(10), S(8)))
        for r in rows:
            divider(t)
            row = tk.Frame(t, bg=SURFACE)
            row.pack(fill="x")
            for i, (_, width, stretch, _) in enumerate(self.COLUMNS):
                row.columnconfigure(i, minsize=S(width), weight=stretch)
            gain_text = (f"{fmt_money(r['gain'], signed=True)} ({fmt_pct(r['gain_pct'])})"
                         if r["gain"] is not None else "—" if r["cost"] is None else "…")
            cells = [(r["symbol"], "body_semi", INK), (r.get("name") or "", "body", MUTED),
                     (f"{r['shares']:,g}", "body", INK), (fmt_money(r["cost"]) if r["cost"] is not None else "add ✎", "body",
                      MUTED if r["cost"] is not None else FAIR),
                     (fmt_price(r["price"]) if r["price"] else "…", "body", INK),
                     (fmt_money(r["value"]) if r["value"] is not None else "…", "body_semi", INK),
                     (fmt_money(r["day"], signed=True) if r["day"] is not None else "", "body", trend_color(r["day"])),
                     (gain_text, "body", trend_color(r["gain"])),
                     (f"{r['value'] / total * 100:.1f}%" if r["value"] and total else "", "small", MUTED)]
            for i, (text, font, fg) in enumerate(cells):
                label(row, text, font, fg=fg).grid(row=0, column=i, sticky=self.COLUMNS[i][3], padx=S(8), pady=S(11))
            actions = tk.Frame(row, bg=SURFACE)
            actions.grid(row=0, column=9, sticky="e", padx=S(8))
            edit = label(actions, "✎", "body", fg=FAINT, cursor="hand2")
            edit.pack(side="left", padx=(0, S(10)))
            remove = label(actions, "✕", "body", fg=FAINT, cursor="hand2")
            remove.pack(side="left")
            make_clickable(row, lambda s=r["symbol"]: self.app.open_symbol(s))
            for w, cmd in ((edit, lambda h=r: self._edit(h)), (remove, lambda s=r["symbol"]: self.app.portfolio.remove(s))):
                w.unbind("<Button-1>")
                w.bind("<Button-1>", lambda e, c=cmd: c())
            row.bind("<Enter>", lambda e, s=r["symbol"]: prefetch(s), add="+")
            add_hover(row, lambda rw=row: set_bg(rw, SAND), lambda rw=row: set_bg(rw, SURFACE))

    def _set_alloc(self, mode):
        self.alloc_mode = mode
        if self.data:
            rows = self._rows()
            self._draw_allocation(rows, sum(r["value"] for r in rows if r["value"]))

    def _draw_allocation(self, rows, total):
        fig = self.alloc_fig
        fig.clear()
        ax = fig.add_subplot(111)
        ax.set_facecolor(SURFACE)
        groups = {}
        for r in rows:
            if r["value"]:
                key = r["symbol"] if self.alloc_mode == "Holdings" else r["sector"]
                groups[key] = groups.get(key, 0) + r["value"]
        items = sorted(groups.items(), key=lambda kv: kv[1], reverse=True)
        if len(items) > 7:
            items = items[:6] + [("Other", sum(v for _, v in items[6:]))]
        if not items or not total:
            self.alloc_canvas.draw_idle()
            return
        wedges, _ = ax.pie([v for _, v in items], colors=PIE_COLORS[:len(items)], startangle=90, counterclock=False,
                           wedgeprops=dict(width=0.36, edgecolor=SURFACE, linewidth=2))
        ax.text(0, 0, f"{fmt_money(total, decimals=0)}\ntotal", ha="center", va="center", fontsize=10, color=INK)
        ax.legend(wedges, [f"{k}   {v / total * 100:.1f}%" for k, v in items], loc="center left",
                  bbox_to_anchor=(1.0, 0.5), frameon=False, fontsize=8.5, labelcolor=MUTED)
        ax.set_aspect("equal")
        fig.subplots_adjust(left=0.0, right=0.6, top=0.97, bottom=0.03)
        self.alloc_canvas.draw_idle()

    def _set_perf_range(self, range_key):
        self.perf_range = range_key
        self._draw_performance()

    def _draw_performance(self):
        self.perf_loader.hide()
        df = self.history
        if df is None or df.empty:
            return
        shares = {h["symbol"]: h["shares"] for h in self.app.portfolio.items}
        cols = [c for c in shares if c in df]
        if not cols or "^GSPC" not in df:
            return
        last = df.index[-1]
        spans = {"1M": 30, "6M": 182, "1Y": 365, "5Y": None}
        if self.perf_range == "YTD":
            part = df[df.index >= last.replace(month=1, day=1, hour=0, minute=0, second=0)]
        elif spans[self.perf_range]:
            part = df[df.index >= last - pd.Timedelta(days=spans[self.perf_range])]
        else:
            part = df
        part = part[cols + ["^GSPC"]].dropna()
        if len(part) < 2:
            return
        value = sum(part[c] * shares[c] for c in cols)
        mine = (value / value.iloc[0] - 1) * 100
        spx = (part["^GSPC"] / part["^GSPC"].iloc[0] - 1) * 100
        fig = self.perf_fig
        fig.clear()
        ax = fig.add_subplot(111)
        style_axes(ax, price_on_right=True)
        ax.set_facecolor(SURFACE)
        x = np.arange(len(part))
        ax.plot(x, mine.to_numpy(), color=ACCENT, linewidth=2, label=f"Your portfolio  {mine.iloc[-1]:+.1f}%")
        ax.plot(x, spx.to_numpy(), color=FAINT, linewidth=1.5, label=f"S&P 500  {spx.iloc[-1]:+.1f}%")
        ax.axhline(0, color=BORDER, linewidth=0.8)
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{v:+.0f}%"))
        ax.set_xlim(0, len(x) - 1)
        set_index_ticks(ax, part.index, self.perf_range)
        ax.legend(loc="upper left", frameon=False, fontsize=8.5, labelcolor=MUTED)
        fig.subplots_adjust(left=0.02, right=0.9, top=0.96, bottom=0.12)
        self.perf_canvas.draw_idle()

    def _render_dividends(self, rows, cost):
        box = self.div_box
        for w in box.winfo_children():
            w.destroy()
        payers = [r for r in rows if r["dividend"]]
        if not payers:
            label(box, "None of your holdings currently pay a dividend.", "body", fg=FAINT).pack(anchor="w",
                                                                                               pady=S(14), padx=S(6))
            return
        grid = tk.Frame(box, bg=SURFACE)
        grid.pack(fill="x")
        heads = [("", "w"), ("PER SHARE / YEAR", "e"), ("SHARES", "e"), ("YEARLY INCOME", "e"), ("YIELD ON COST", "e")]
        for c, (h, anchor) in enumerate(heads):
            grid.columnconfigure(c, weight=1 if c else 0, minsize=S(90))
            label(grid, h, "eyebrow", fg=FAINT).grid(row=0, column=c, sticky=anchor, padx=S(8), pady=(S(8), S(6)))
        for i, r in enumerate(sorted(payers, key=lambda r: r["income"], reverse=True), start=1):
            vals = [(r["symbol"], "body_semi", INK), (fmt_money(r["dividend"]), "body", INK),
                    (f"{r['shares']:,g}", "body", MUTED), (fmt_money(r["income"]), "body_semi", UP),
                    (f"{r['dividend'] / r['cost'] * 100:.2f}%" if r["cost"] else "—", "body", MUTED)]
            for c, (text, font, fg) in enumerate(vals):
                label(grid, text, font, fg=fg).grid(row=i, column=c, sticky=heads[c][1], padx=S(8), pady=S(6))
        total = sum(r["income"] for r in payers)
        divider(box, pady=(S(6), 0))
        foot = tk.Frame(box, bg=SURFACE)
        foot.pack(fill="x", pady=S(8))
        label(foot, f"About {fmt_money(total)} a year · {fmt_money(total / 12)} a month on average", "body_semi",
              fg=UP).pack(side="right", padx=S(8))

    def _screenshot_allocation(self):
        save_screenshot(self.app, figure_image(self.alloc_fig), "Portfolio allocation",
                        chart_caption(f"Portfolio allocation by {self.alloc_mode.lower()}"))

    def _screenshot_performance(self):
        save_screenshot(self.app, figure_image(self.perf_fig), "Portfolio performance",
                        chart_caption("Portfolio vs S&P 500", self.perf_range))


# -------------------------------------------------------------- Calendar ------
class CalendarPage(Page):
    refresh_ms = 30 * 60_000
    FILTERS = {"All": None, "Earnings": "earnings", "Dividends": "dividend", "The Fed": "fed", "Economy": "economy"}

    @staticmethod
    def type_style(kind):
        return {"earnings": ("EARNINGS", ACCENT, ACCENT_SOFT), "dividend": ("DIVIDEND", UP, UP_SOFT),
                "fed": ("THE FED", "#5B7FA6", blend("#5B7FA6", SURFACE, 0.85)),
                "economy": ("ECONOMY", FAIR, FAIR_SOFT)}[kind]

    def build(self):
        self.result, self.filter = None, None
        self.scroller = ScrollFrame(self)
        self.scroller.pack(fill="both", expand=True)
        wrap = tk.Frame(self.scroller.inner, bg=BG)
        wrap.pack(fill="both", expand=True, padx=S(56), pady=(0, S(40)))
        head = self.page_header(wrap, "Calendar", "Earnings, dividends, Fed meetings and key economic reports "
                                                  "for the next four months.")
        RoundButton(head, "Refresh", self.reload, kind="ghost").pack(side="right", anchor="s")
        self.chips = ChipGroup(wrap, list(self.FILTERS), self._set_filter, value="All")
        self.chips.pack(anchor="w", pady=(0, S(18)))
        cols = tk.Frame(wrap, bg=BG)
        cols.pack(fill="both", expand=True)
        cols.columnconfigure(0, weight=3, uniform="cal")
        cols.columnconfigure(1, weight=1, uniform="cal")
        self.list = tk.Frame(cols, bg=BG)
        self.list.grid(row=0, column=0, sticky="nsew", padx=(0, S(24)))
        side = tk.Frame(cols, bg=BG)
        side.grid(row=0, column=1, sticky="nsew")
        nxt = card(side)
        nxt.pack(fill="x")
        nbox = tk.Frame(nxt, bg=SURFACE)
        nbox.pack(fill="both", expand=True, padx=S(20), pady=S(18))
        label(nbox, "Coming Up", "h2").pack(anchor="w", pady=(0, S(8)))
        self.next_box = tk.Frame(nbox, bg=SURFACE)
        self.next_box.pack(fill="x")
        about = tk.Frame(side, bg=SAND)
        about.pack(fill="x", pady=(S(18), 0))
        abox = tk.Frame(about, bg=SAND)
        abox.pack(fill="both", expand=True, padx=S(20), pady=S(18))
        label(abox, "ABOUT THIS CALENDAR", "eyebrow", fg=ACCENT).pack(anchor="w")
        self.about = wrap_label(abox, "", "small", fg=MUTED)
        self.about.pack(fill="x", pady=(S(6), 0))
        for w in (self.app.watchlist, self.app.portfolio):
            w.listeners.append(lambda: self.loaded and self.refresh())

    def first_load(self):
        self.refresh()

    def _symbols(self):
        return list(dict.fromkeys(self.app.portfolio.symbols + self.app.watchlist.symbols))

    def refresh(self):
        symbols = self._symbols()
        if self.result is None:
            show_skeleton(self.list, blocks=6, lines=2, pady=20)
        self.app.worker.run(lambda: fetch_calendar(symbols), self._got,
                            lambda e: self._message("Couldn't load the calendar. Check your connection."))

    def reload(self):
        with _CACHE_LOCK:
            for key in [k for k in _CACHE if k[0] in ("economic-calendar", "calendar")]:
                del _CACHE[key]
        self.refresh()

    def _message(self, text):
        for w in self.list.winfo_children():
            w.destroy()
        label(self.list, text, "body", fg=DOWN).pack(anchor="w", pady=S(12))

    def _got(self, result):
        self.result = result
        self._render()

    def _set_filter(self, choice):
        self.filter = self.FILTERS[choice]
        self._render()

    def _render(self):
        events = [e for e in self.result["events"] if self.filter in (None, e["type"])]
        for w in self.list.winfo_children():
            w.destroy()
        if not events:
            label(self.list, "Nothing scheduled in this category for the next few months.", "body",
                  fg=FAINT).pack(anchor="w", pady=S(12))
        today = datetime.now().date()
        current = None
        for e in events[:160]:
            day = e["date"].date()
            if day != current:
                current = day
                when = (e["date"].strftime("%A, %B %d").replace(" 0", " "))
                delta = (day - today).days
                rel = "Today" if delta == 0 else "Tomorrow" if delta == 1 else f"in {delta} days"
                head = tk.Frame(self.list, bg=BG)
                head.pack(fill="x", pady=(S(18), S(4)))
                label(head, when, "card_title").pack(side="left")
                label(head, rel, "small", fg=ACCENT if delta <= 1 else FAINT).pack(side="left", padx=S(10))
                divider(self.list)
            self._event_row(e)
        self._render_next()
        n = len(self._symbols())
        failed = self.result["failed"]
        self.about.configure(text=f"Earnings and dividends are shown for the {n} stocks in your watchlist and "
                                  "portfolio. Fed meetings come from the Federal Reserve; CPI and jobs reports from "
                                  "the Bureau of Labor Statistics; GDP and PCE inflation from the Bureau of Economic "
                                  "Analysis; retail sales from the Census Bureau. Release times are Eastern."
                                  + (f"\n\nCouldn't reach: {', '.join(failed)}." if failed else ""))

    def _event_row(self, e):
        word, fg, soft = self.type_style(e["type"])
        row = tk.Frame(self.list, bg=BG)
        row.pack(fill="x")
        inner = tk.Frame(row, bg=BG)
        inner.pack(fill="x", padx=S(6), pady=S(9))
        pill = label(inner, word, "eyebrow", fg=fg, bg=soft, width=10, pady=S(3))
        pill.keep_bg = True
        pill.pack(side="left", anchor="n", padx=(0, S(14)))
        text = tk.Frame(inner, bg=BG)
        text.pack(side="left", fill="x", expand=True)
        label(text, e["title"], "body_semi").pack(anchor="w")
        if e["detail"]:
            label(text, e["detail"], "small", fg=MUTED).pack(anchor="w")
        if e.get("time"):
            label(inner, e["time"], "small", fg=FAINT).pack(side="right", anchor="n")
        if e.get("symbol"):
            make_clickable(row, lambda s=e["symbol"]: self.app.open_symbol(s))
            add_hover(row, lambda: set_bg(row, SAND), lambda: set_bg(row, BG))

    def _render_next(self):
        for w in self.next_box.winfo_children():
            w.destroy()
        today = datetime.now().date()
        picks = []
        for kind, title in (("fed", "Fed decision"), ("CPI", "Inflation (CPI)"), ("Jobs", "Jobs report"),
                            ("GDP", "GDP"), ("earnings", "Next earnings")):
            for e in self.result["events"]:
                if (e["type"] == kind) or (kind in ("CPI", "Jobs", "GDP") and e["title"].startswith(
                        {"CPI": "Consumer Price", "Jobs": "Jobs", "GDP": "GDP"}[kind])):
                    picks.append((title, e))
                    break
        if not picks:
            label(self.next_box, "Nothing scheduled.", "small", fg=FAINT).pack(anchor="w")
        for i, (title, e) in enumerate(picks):
            if i:
                divider(self.next_box)
            row = tk.Frame(self.next_box, bg=SURFACE)
            row.pack(fill="x", pady=S(7))
            label(row, title.upper(), "eyebrow", fg=MUTED).pack(anchor="w")
            delta = (e["date"].date() - today).days
            rel = "today" if delta == 0 else "tomorrow" if delta == 1 else f"in {delta} days"
            label(row, e["date"].strftime("%a, %b %d").replace(" 0", " ") + f"  ·  {rel}", "body_semi").pack(anchor="w")
            if e["type"] == "earnings":
                label(row, e["title"].replace(" earnings", ""), "small", fg=FAINT).pack(anchor="w")


# -----------------------------------------------------------------------------
# 9. The application window
# -----------------------------------------------------------------------------
try:    # optional: lets people drag a portfolio CSV onto the window
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DropSupport = TkinterDnD.DnDWrapper
except Exception:
    DND_FILES, TkinterDnD = None, None

    class _DropSupport:
        pass


class App(tk.Tk, _DropSupport):
    PAGES = [("Home", HomePage), ("Markets", MarketsPage), ("News", NewsPage), ("Watchlist", WatchlistPage),
             ("Portfolio", PortfolioPage), ("Calendar", CalendarPage), ("Bond Market", BondPage)]

    def __init__(self):
        global SCALE
        super().__init__()
        SCALE = self.winfo_fpixels("1i") / 96
        self.settings = load_settings()
        apply_theme(self.settings.get("theme") or ("dark" if windows_prefers_dark() else "light"))
        self.restart = False
        self.suggesters = []
        self.title(APP_NAME)
        self.configure(bg=BG)
        self._size_window()
        self._set_icon()
        init_fonts(self)
        init_ttk(self)

        self.worker = Worker(self)
        self.watchlist = WatchlistStore()
        self.visited = set()   # headlines opened this session are shown in gray
        self.news = SharedFetch(self.worker, fetch_all_news, max_age=10 * 60)
        self.milton = SharedFetch(self.worker, fetch_milton_articles, max_age=30 * 60)
        self.portfolio = PortfolioStore()
        self.alerts = AlertStore()

        self._build_header()
        self._build_footer()
        self.body = tk.Frame(self, bg=BG)
        self.body.pack(fill="both", expand=True)

        self.pages = {name: cls(self) for name, cls in self.PAGES}
        self.pages["Source"] = SourcePage(self)
        self.current = None
        start = self.settings.get("page", "Home")
        self.navigate(start if start in self.pages and start != "Source" else "Home")
        self.after(1500, lambda: self.news.get(lambda n: None, lambda e: None))  # warm the news cache

        self.bind_all("<MouseWheel>", self._on_wheel)
        for i, (name, _) in enumerate(self.PAGES, start=1):
            self.bind_all(f"<Control-Key-{i}>", lambda e, n=name: self.navigate(n))
        self.bind_all("<Control-f>", lambda e: self._focus_search())
        self.bind_all("<Escape>", lambda e: self._key(e, self.go_back))
        self.bind_all("<Alt-Left>", lambda e: self._key(e, self.go_back))
        self.bind_all("<F1>", lambda e: ShortcutsDialog.open(self))
        self.bind_all("<F5>", lambda e: self._key(e, self.reload_page))
        self.bind_all("<Control-r>", lambda e: self._key(e, self.reload_page))
        self.bind_all("<Control-s>", lambda e: self._key(e, self.screenshot_page))
        self.bind_all("<Left>", lambda e: self._key(e, lambda: self._step_range(-1), typing_blocks=True))
        self.bind_all("<Right>", lambda e: self._key(e, lambda: self._step_range(1), typing_blocks=True))
        for key, how in (("<Prior>", ("scroll", -1, "pages")), ("<Next>", ("scroll", 1, "pages")),
                         ("<Home>", ("moveto", 0)), ("<End>", ("moveto", 1))):
            self.bind_all(key, lambda e, h=how: self._key(e, lambda: self._scroll_page(h), typing_blocks=True))
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(5000, self._check_alerts)
        self._enable_drop()
        self.bind("<Configure>", lambda e: e.widget is self and self._close_suggestions())
        set_dark_titlebar(self, THEME == "dark")
        self._tick()

    # --- window setup -----------------------------------------------------------
    def _size_window(self):
        sw, sh = self.winfo_screenwidth(), self.winfo_screenheight()
        w, h = min(S(1400), int(sw * 0.92)), min(S(900), int(sh * 0.88))
        self.minsize(min(S(1100), w), min(S(680), h))
        saved = re.match(r"(\d+)x(\d+)\+(-?\d+)\+(-?\d+)$", self.settings.get("geometry", ""))
        if saved:   # reopen where you left it, as long as it still fits on this screen
            sw_, sh_, sx, sy = map(int, saved.groups())
            if sw_ <= sw and sh_ <= sh and -20 <= sx <= sw - 200 and 0 <= sy <= sh - 200:
                self.geometry(saved.group(0))
                if self.settings.get("zoomed"):
                    self.after(10, lambda: self.state("zoomed"))
                return
        self.geometry(f"{w}x{h}+{(sw - w) // 2}+{max((sh - h) // 2 - S(20), 0)}")

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
            logo = themed_logo()
            logo = Image.alpha_composite(Image.new("RGBA", logo.size, BG), logo).convert("RGB")
            h = S(46)
            logo = logo.resize((int(logo.width * h / logo.height), h), Image.LANCZOS)
            self._logo = ImageTk.PhotoImage(logo)
            brand = tk.Label(bar, image=self._logo, bg=BG, cursor="hand2")
        except Exception:
            brand = label(bar, APP_NAME, "h2", cursor="hand2")
        brand.grid(row=0, column=0, sticky="w")
        brand.bind("<Button-1>", lambda e: self.navigate("Home"))

        nav = tk.Frame(bar, bg=BG)
        nav.grid(row=0, column=1)
        self.nav_links = {}
        for name, _ in self.PAGES:
            link = label(nav, name, "nav", cursor="hand2")
            link.pack(side="left", padx=S(14))
            link.bind("<Button-1>", lambda e, n=name: self.navigate(n))
            link.bind("<Enter>", lambda e, l=link: l.configure(fg=ACCENT))
            link.bind("<Leave>", lambda e, n=name, l=link: l.configure(fg=ACCENT if n == self._active_nav() else INK))
            self.nav_links[name] = link

        right = tk.Frame(bar, bg=BG)
        right.grid(row=0, column=2, sticky="e")
        RoundButton(right, "Subscribe", lambda: open_link(SITE_URL), radius=12).pack(side="right")
        ThemeToggle(right, self.toggle_theme).pack(side="right", padx=(0, S(14)))
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
        keys = label(inner, "Shortcuts (F1)", "small", fg=ACCENT, cursor="hand2")
        keys.pack(side="right", padx=(0, S(24)))
        keys.bind("<Button-1>", lambda e: ShortcutsDialog.open(self))
        idea = label(inner, "Send an idea", "small", fg=ACCENT, cursor="hand2")
        idea.pack(side="right", padx=(0, S(18)))
        idea.bind("<Button-1>", lambda e: FeedbackDialog.open(self))
        label(inner, f"© {datetime.now().year} The Milton Review  ·  Not financial advice", "small",
              fg=FAINT).pack(side="right", padx=S(24))

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
        self.update_title()
        active = self._active_nav()
        for n, link in self.nav_links.items():
            link.configure(fg=ACCENT if n == active else INK,
                           font=FONTS["nav_active"] if n == active else FONTS["nav"])

    def _active_nav(self):
        return "News" if self.current == "Source" else self.current

    def navigate(self, name):
        """Header links: Markets always opens on the general market overview."""
        self.show(name)
        if name == "Markets":
            self.pages["Markets"].show_overview()

    def show_source(self, source_id):
        self.show("Source")
        self.pages["Source"].open(source_id)

    def open_symbol(self, symbol):
        self.show("Markets")
        self.pages["Markets"].load(symbol)

    def update_title(self, detail=None):
        page = self.current or ""
        if page == "Source" and self.pages["Source"].source:
            detail, page = self.pages["Source"].source["name"], "News"
        self.title(" — ".join(x for x in (APP_NAME, page, detail) if x))

    # --- keyboard -----------------------------------------------------------------------
    def _key(self, event, action, typing_blocks=False):
        """Run a shortcut only for the main window, and not while typing if it would clash."""
        try:
            if event.widget.winfo_toplevel() is not self:
                return
        except (AttributeError, tk.TclError):
            return
        if typing_blocks and isinstance(self.focus_get(), tk.Entry):
            return
        action()
        return "break"

    def go_back(self):
        if self.current == "Source":
            self.navigate("News")
        elif self.current == "Markets" and self.pages["Markets"].mode != "overview":
            self.pages["Markets"].show_overview()
        elif isinstance(self.focus_get(), tk.Entry):
            self.focus_set()

    def reload_page(self):
        page = self.pages[self.current]
        if self.current == "Source" and page.source:
            self.news.get(lambda n: page.open(page.source["id"]), force=True)
        elif hasattr(page, "reload"):
            page.reload()
        else:
            page.refresh()
        self.set_status("Refreshing…")

    def screenshot_page(self):
        page = self.pages[self.current]
        if hasattr(page, "screenshot"):
            page.screenshot()

    def _step_range(self, step):
        if self.current == "Markets":
            self.pages["Markets"].step_range(step)

    def _scroll_page(self, how):
        scroller = getattr(self.pages[self.current], "scroller", None)
        if scroller is None:
            return
        if how[0] == "scroll":
            scroller.canvas.yview_scroll(how[1], how[2])
        else:
            scroller.canvas.yview_moveto(how[1])

    # --- drag & drop ---------------------------------------------------------------------
    def _enable_drop(self):
        """Let people drop a portfolio CSV onto the window (needs the tkinterdnd2 package)."""
        if TkinterDnD is None:
            return
        try:
            TkinterDnD._require(self)
        except Exception as exc:
            print(f"Drag & drop unavailable: {exc}")
            return
        portfolio = self.pages["Portfolio"]
        for widget in (self, self.body, portfolio, portfolio.scroller.canvas, portfolio.scroller.inner):
            try:
                widget.drop_target_register(DND_FILES)
                widget.dnd_bind("<<Drop>>", self._on_drop)
                widget.dnd_bind("<<DropEnter>>", lambda e: (self.set_status("Drop a CSV to import it into your "
                                                                            "portfolio"), e.action)[1])
                widget.dnd_bind("<<DropLeave>>", lambda e: (self.set_status(""), e.action)[1])
            except Exception as exc:
                print(f"Couldn't enable drag & drop on {widget}: {exc}")

    def _on_drop(self, event):
        files = [f for f in self.tk.splitlist(event.data)]
        csvs = [f for f in files if f.lower().endswith((".csv", ".txt"))]
        if not csvs:
            self.set_status("Only CSV files can be imported — save your spreadsheet as CSV first.")
            return event.action
        self.navigate("Portfolio")
        self.pages["Portfolio"].import_csv(csvs[0])
        return event.action

    # --- price alerts ------------------------------------------------------------------
    def _check_alerts(self):
        """Every minute: fetch prices for active alerts and fire any that are hit."""
        active = self.alerts.active()
        if active:
            symbols = list(dict.fromkeys(a["symbol"] for a in active))
            self.worker.run(lambda: fetch_quotes(symbols), self._evaluate_alerts, lambda e: None)
        self.after(60_000, self._check_alerts)

    def _evaluate_alerts(self, quotes):
        fired = []
        for a in self.alerts.active():
            q = quotes.get(a["symbol"])
            if q and alert_hit(a, q):
                a["triggered"] = datetime.now().isoformat(timespec="minutes")
                a["price"] = q["last"]
                fired.append((a, q))
        if not fired:
            return
        self.alerts.save()
        for a, q in fired:
            title = f"{a['symbol']} price alert"
            body = f"{describe_alert(a)} — now {fmt_price(q['last'])} ({fmt_pct(q['pct'])} today)"
            windows_notify(title, body)
            self.show_banner(f"🔔  {title}: {body}", "View", lambda s=a["symbol"]: self.open_symbol(s))

    def show_banner(self, text, action_text=None, action=None):
        """A dismissable strip under the header for things that need attention."""
        if getattr(self, "banner", None) is not None:
            self.banner.destroy()
        bar = tk.Frame(self, bg=ACCENT_SOFT)
        bar.pack(fill="x", before=self.body)
        inner = tk.Frame(bar, bg=ACCENT_SOFT)
        inner.pack(fill="x", padx=S(40), pady=S(8))
        label(inner, text, "body_semi", fg=INK, bg=ACCENT_SOFT).pack(side="left")
        close = label(inner, "✕", "body", fg=MUTED, bg=ACCENT_SOFT, cursor="hand2")
        close.pack(side="right")
        close.bind("<Button-1>", lambda e: bar.destroy())
        if action:
            link = label(inner, action_text + " →", "body_semi", fg=ACCENT, bg=ACCENT_SOFT, cursor="hand2")
            link.pack(side="right", padx=S(16))
            link.bind("<Button-1>", lambda e: (bar.destroy(), action()))
        self.banner = bar
        self.after(30_000, lambda: bar.winfo_exists() and bar.destroy())

    def toggle_theme(self):
        """Switch light/dark: remember the choice and rebuild the window in the new colours."""
        self.settings["theme"] = "light" if THEME == "dark" else "dark"
        self.restart = True
        self._on_close()

    def _close_suggestions(self):
        for suggester in self.suggesters:
            suggester.close()

    def _on_close(self):
        self.settings["zoomed"] = self.state() == "zoomed"
        if self.state() == "normal":
            self.settings["geometry"] = self.geometry()
        self.settings["page"] = self._active_nav()
        save_settings(self.settings)
        self.destroy()

    def _focus_search(self):
        page = self.pages[self.current]
        target = getattr(page, "search", None) or getattr(page, "entry", None)
        if target:
            target.focus()

    def set_status(self, text):
        self.status_label.configure(text=text)

    # --- events -----------------------------------------------------------------------
    def _on_wheel(self, event):
        self._close_suggestions()
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
    while app.restart:     # switching light/dark rebuilds the window
        app = App()
        app.mainloop()


if __name__ == "__main__":
    main()
