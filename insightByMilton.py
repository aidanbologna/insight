# =============================================================================
#  Insight by Milton
#  A desktop markets companion for The Milton Review (themiltonreview.net)
#
#  Pages:  Home · Markets · News · Watchlist · Bond Market
#  Data:   Yahoo Finance (yfinance), U.S. Treasury, The Milton Review RSS feed
# =============================================================================

import html
import importlib
import io
import json
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


def fetch_info(symbol):
    return _cached(("info", symbol), 5 * 60, lambda: _fetch_info(symbol))


def _fetch_info(symbol):
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
    ("Ctrl + 1 … 5", "Go to Home, Markets, News, Watchlist or Bond Market"),
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


_LOGO = None


def _caption_font(size):
    for name in ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def add_watermark(img, caption=""):
    """Add a footer strip: caption on the left, the Insight by Milton logo in the bottom-right corner."""
    global _LOGO
    if _LOGO is None:
        _LOGO = Image.open(resource_path("assets", "logo.png")).convert("RGBA")
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

    def __init__(self, parent, app, article, bg=BG, summary=True, show_source=True):
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
        if cls.instance is not None and cls.instance.winfo_exists():
            cls.instance.lift()
            return
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
        RoundButton(search, "Search", self.do_search).pack(side="left", padx=(S(10), 0))

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
        self.canvas.mpl_connect("figure_leave_event", lambda e: self._hide_hover())

        self.fund_section = tk.Frame(main, bg=BG)   # only packed for companies, see _fill_fundamentals
        self.headlines_title = label(main, "Related Financial News", "h2")
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
        self.app.worker.run(lambda: fetch_index_history(rk),
                            lambda df: self._draw_index_chart(rid, rk, df))

    def _draw_index_chart(self, rid, range_key, df):
        if rid != self.overview_id or df.empty:
            return
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
        if mode == "overview":
            self.detail.pack_forget()
            self.overview.pack(fill="both", expand=True)
        else:
            self.overview.pack_forget()
            self.detail.pack(fill="both", expand=True)
        self.scroller.to_top()

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
        self._chart_message(f"Loading {query.upper()}…")
        self.app.set_status(f"Loading {query.upper()}…")
        self.app.worker.run(lambda: load_symbol(query, rk),
                            lambda d: self._show(rid, d), lambda e: self._failed(rid, e))

    def set_range(self, range_key):
        self.range_key = range_key
        self.range_chips.set(range_key)
        if not self.data:
            return
        self.request_id += 1
        rid, sym = self.request_id, self.data["symbol"]
        slow = self.after(250, lambda: rid == self.request_id and self._chart_message("Loading…"))
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
        label(self.news_box, "Looking through today's headlines…", "body", fg=FAINT).pack(anchor="w")

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
        label(self.list, f"Loading headlines from {len(NEWS_SOURCES)} outlets…", "body",
              fg=FAINT).pack(anchor="w", pady=S(12))
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
        label(self.stories, "Loading…", "body", fg=FAINT).pack(anchor="w")
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
        self.settings = load_settings()
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
            logo = Image.open(resource_path("assets", "logo.png")).convert("RGBA")
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
            link.pack(side="left", padx=S(18))
            link.bind("<Button-1>", lambda e, n=name: self.navigate(n))
            link.bind("<Enter>", lambda e, l=link: l.configure(fg=ACCENT))
            link.bind("<Leave>", lambda e, n=name, l=link: l.configure(fg=ACCENT if n == self._active_nav() else INK))
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
        keys = label(inner, "Shortcuts (F1)", "small", fg=ACCENT, cursor="hand2")
        keys.pack(side="right", padx=(0, S(24)))
        keys.bind("<Button-1>", lambda e: ShortcutsDialog.open(self))
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
        elif self.current == "Markets" and self.pages["Markets"].mode == "detail":
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
