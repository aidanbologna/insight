"""Tests for the web server: the shared cache, the limits and the main answers.

Everything runs against a pretend data source and a pretend clock, so the tests are quick, give the
same result every time and never contact Yahoo. Set INSIGHT_LIVE_TEST=1 to add one real request.
"""

import math
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import insight_core as core
from web import service as service_module
from web.app import create_app
from web.config import Settings
from web.limits import BadRequest, VisitorLimiter, clean_query, clean_range, clean_symbol, clean_symbols
from web.service import DataService, Pacer
from web.source import DETAIL_FIELDS, MarketSource, SourceBusy, SourceFailed

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# --- stand-ins ---------------------------------------------------------------------------------------
class Clock:
    """A clock the test moves by hand. Sleeping just moves it forward."""

    def __init__(self):
        self.now = 1_800_000_000.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def a_quote(last=100.0, prev=98.0):
    return {"last": last, "prev": prev, "change": last - prev, "pct": (last / prev - 1) * 100, "high": last + 1,
            "low": last - 1, "volume": 1_000_000.0, "spark": [prev - 1, prev, last]}


APPLE = {"symbol": "AAPL", "shortName": "Apple Inc.", "longName": "Apple Inc.", "quoteType": "EQUITY",
         "fullExchangeName": "NasdaqGS", "currency": "USD", "sector": "Technology",
         "industry": "Consumer Electronics", "longBusinessSummary": "Makes phones.",
         "regularMarketPrice": 200.0, "regularMarketPreviousClose": 196.0, "regularMarketOpen": 197.0,
         "regularMarketDayLow": 195.5, "regularMarketDayHigh": 201.0, "regularMarketVolume": 50_000_000,
         "averageVolume": 45_000_000, "fiftyTwoWeekLow": 150.0, "fiftyTwoWeekHigh": 210.0,
         "marketCap": 3.0e12, "trailingPE": 30.0, "forwardPE": 14.0, "trailingEps": 6.5, "beta": 1.1,
         "profitMargins": 0.25, "grossMargins": 0.45, "returnOnEquity": 0.30, "revenueGrowth": 0.05,
         "debtToEquity": 80.0, "payoutRatio": 0.0}
FUND = {"symbol": "SPY", "shortName": "SPDR S&P 500 ETF Trust", "quoteType": "ETF",
        "regularMarketPrice": 500.0, "regularMarketPreviousClose": 505.0}
REPORTED = datetime(2026, 11, 2, 21, 0, tzinfo=timezone.utc)
EARNINGS = {"last": {"date": REPORTED, "timing": "after the market closes", "eps": 2.10, "estimate": 1.98,
                     "surprise": 5.8, "revenue": 114.5e9, "revenue_growth": 11.7,
                     "quarter": datetime(2026, 9, 30), "net_income": 30.7e9, "net_income_prev": 27.5e9,
                     "reaction": (-1.9, "the next trading day")},
            "next": {"date": REPORTED + timedelta(days=87), "timing": "after the market closes",
                     "time": "4:00 PM ET", "estimate": 2.91},
            "record": [(REPORTED - timedelta(days=91), 3.4), (REPORTED, 5.8)]}


class FakeSource(MarketSource):
    """A data source with made-up numbers that counts how often it is asked."""
    name = "Test data"

    def __init__(self):
        self.calls = {"quotes": [], "history": [], "details": [], "earnings": [], "search": []}
        self.known = {symbol for _, symbol, _ in core.SNAPSHOT} | {"AAPL", "MSFT", "SPY"}
        self.backoff = 0.0
        self.error = None           # raise this instead of answering
        self.gate = None            # a threading.Event to wait for, to make a download slow
        self.volume = 1_000_000.0

    def _work(self, kind, what):
        self.calls[kind].append(what)
        if self.gate is not None:
            self.gate.wait(5)
        if self.error is not None:
            raise self.error

    def quotes(self, symbols):
        self._work("quotes", list(symbols))
        return {s: dict(a_quote(), volume=self.volume) for s in symbols if s in self.known}

    def history(self, symbol, range_key):
        self._work("history", (symbol, range_key))
        if symbol not in self.known:
            return None
        return {"interval": core.RANGES[range_key][1], "t": [1, 2, 3], "open": [1.0, 2.0, 3.0],
                "high": [1.5, 2.5, 3.5], "low": [0.5, 1.5, 2.5], "close": [1.2, 2.2, 3.2],
                "volume": [10.0, 20.0, 30.0], "ma50": [None, None, 2.2], "ma200": [None, None, None]}

    def details(self, symbol):
        self._work("details", symbol)
        return {"AAPL": dict(APPLE), "SPY": dict(FUND)}.get(symbol)

    def earnings(self, symbol):
        self._work("earnings", symbol)
        return EARNINGS if symbol == "AAPL" else None

    def search(self, query):
        self._work("search", query)
        return [{"symbol": "AAPL", "name": "Apple Inc.", "type": "Equity", "exchange": "NASDAQ"}] \
            if "apple" in query.lower() else []

    def backoff_seconds(self):
        return self.backoff

    def is_rate_limit(self, error):
        return "Too Many Requests" in str(error)


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def source():
    return FakeSource()


@pytest.fixture
def service(source, clock):
    return DataService(source, per_minute=0, clock=clock, sleep=clock.sleep)     # 0 = no ceiling


def make_client(source, clock, **settings):
    app = create_app(source=source, settings=Settings(**settings), clock=clock, sleep=clock.sleep)
    return TestClient(app)


@pytest.fixture
def client(source, clock):
    return make_client(source, clock)


# --- the shared core ---------------------------------------------------------------------------------
def test_core_and_server_load_without_the_desktop_libraries():
    code = ("import sys, insight_core, web.app; "
            "print([m for m in ('tkinter', 'matplotlib', 'PIL') if m in sys.modules])")
    env = dict(os.environ)
    if env.get("INSIGHT_REAL_APPDATA"):              # conftest pointed APPDATA at a scratch folder
        env["APPDATA"] = env["INSIGHT_REAL_APPDATA"]
    result = subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, capture_output=True, text=True,
                            timeout=120)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "[]"


def test_lifetimes_match_the_windows_app():
    assert service_module.QUOTE_TTL == core.QUOTE_TTL == 55
    assert service_module.HISTORY_TTL_DAILY == 15 * 60
    assert service_module.HISTORY_TTL_INTRADAY == 60
    assert service_module.DETAILS_TTL == 5 * 60
    assert service_module.EARNINGS_TTL == 6 * 3600


# --- the cache -----------------------------------------------------------------------------------------
def test_an_answer_is_reused_until_its_lifetime_ends(service, source, clock):
    service.quotes(["AAPL"])
    clock.now += 54
    priced, _ = service.quotes(["AAPL"])
    assert len(source.calls["quotes"]) == 1
    assert priced["AAPL"].stale is False
    clock.now += 2                                   # 56 seconds old: past the 55-second lifetime
    service.quotes(["AAPL"])
    assert len(source.calls["quotes"]) == 2


@pytest.mark.parametrize("ask, lifetime", [
    (lambda s: s.history("AAPL", "1Y"), 15 * 60),
    (lambda s: s.history("AAPL", "1D"), 60),
    (lambda s: s.details("AAPL"), 5 * 60),
    (lambda s: s.earnings("AAPL"), 6 * 3600),
    (lambda s: s.search("apple"), 10 * 60),
])
def test_each_kind_of_answer_has_its_own_lifetime(service, source, clock, ask, lifetime):
    ask(service)
    clock.now += lifetime - 1
    ask(service)
    assert sum(len(calls) for calls in source.calls.values()) == 1
    clock.now += 2
    ask(service)
    assert sum(len(calls) for calls in source.calls.values()) == 2


def test_only_the_symbols_not_in_memory_are_fetched(service, source):
    service.quotes(["AAPL", "MSFT"])
    priced, missing = service.quotes(["MSFT", "SPY", "AAPL"])
    assert source.calls["quotes"] == [["AAPL", "MSFT"], ["SPY"]]
    assert set(priced) == {"AAPL", "MSFT", "SPY"} and missing == []


def test_identical_requests_at_the_same_moment_share_one_download(service, source):
    source.gate = threading.Event()
    results = []
    threads = [threading.Thread(target=lambda: results.append(service.quotes(["AAPL"]))) for _ in range(8)]
    for thread in threads:
        thread.start()
    deadline = time.time() + 5
    while not source.calls["quotes"] and time.time() < deadline:
        time.sleep(0.01)
    time.sleep(0.2)                                  # give the other seven time to queue up behind the first
    source.gate.set()
    for thread in threads:
        thread.join(10)
    assert len(source.calls["quotes"]) == 1
    assert len(results) == 8 and all(priced["AAPL"].value["last"] == 100.0 for priced, _ in results)
    assert service.cache["joined"] == 7 and service.cache["fetched"] == 1


def test_an_unknown_symbol_is_remembered_briefly(service, source, clock):
    priced, missing = service.quotes(["NOPE"])
    assert priced == {} and missing == ["NOPE"]
    service.quotes(["NOPE"])
    assert len(source.calls["quotes"]) == 1
    clock.now += service_module.UNKNOWN_TTL + 1
    service.quotes(["NOPE"])
    assert len(source.calls["quotes"]) == 2
    assert service.fetches["quotes"]["empty"] == 2


def test_an_empty_answer_never_replaces_a_real_one(service, source, clock):
    service.quotes(["AAPL"])
    source.known.discard("AAPL")                     # the source hiccups and returns nothing
    clock.now += 60
    priced, _ = service.quotes(["AAPL"])
    assert priced["AAPL"].value["last"] == 100.0 and priced["AAPL"].stale is True


def test_a_cut_short_answer_is_asked_for_again_soon(service, source, clock):
    source.details = lambda symbol: source.calls["details"].append(symbol) or dict(APPLE, partial=True)
    service.details("AAPL")
    clock.now += service_module.PARTIAL_TTL + 1
    service.details("AAPL")
    assert len(source.calls["details"]) == 2


def test_memory_is_bounded(source, clock):
    small = DataService(source, per_minute=0, max_entries=20, clock=clock, sleep=clock.sleep)
    for i in range(60):
        clock.now += 1
        small.search(f"company {i}")
    assert len(small._entries) <= 20


def test_charts_count_for_more_than_prices(source, clock):
    small = DataService(source, per_minute=0, max_numbers=100, clock=clock, sleep=clock.sleep)
    symbols = [symbol for _, symbol, _ in core.SNAPSHOT]
    for symbol in symbols:                           # each pretend chart holds 25 numbers
        clock.now += 1
        small.history(symbol, "1Y")
    assert small._numbers <= 100 and len(small._entries) <= 4
    assert small._numbers == sum(entry.weight for entry in small._entries.values())
    small.history(symbols[-1], "1Y")                 # the newest one is still in memory
    assert len(source.calls["history"]) == len(symbols)


# --- going easy on the source ------------------------------------------------------------------------
def test_while_the_source_says_slow_down_older_answers_are_served(service, source, clock):
    service.quotes(["AAPL"])
    clock.now += 600
    source.backoff = 180
    priced, _ = service.quotes(["AAPL"])
    assert priced["AAPL"].stale is True
    assert len(source.calls["quotes"]) == 1          # the source was left alone
    assert service.ceiling["held_back"] == 1
    assert "slow down" in service.notice()

    with pytest.raises(SourceBusy) as busy:          # nothing in memory for this one
        service.quotes(["MSFT"])
    assert busy.value.retry_after == 180
    assert len(source.calls["quotes"]) == 1

    source.backoff = 0                               # the time-out ends: asking starts again
    priced, _ = service.quotes(["AAPL"])
    assert priced["AAPL"].stale is False and len(source.calls["quotes"]) == 2


def test_too_many_requests_is_counted_and_the_older_answer_kept(service, source, clock):
    service.details("AAPL")
    clock.now += 600
    source.error = RuntimeError("Too Many Requests. Rate limited. Try after a while.")
    answer = service.details("AAPL")
    assert answer.stale is True and answer.value["shortName"] == "Apple Inc."
    assert service.fetches["details"] == {"ok": 1, "empty": 0, "failed": 0, "rate_limited": 1}
    assert service.problems[0]["outcome"] == "rate_limited"
    with pytest.raises(SourceBusy):
        service.details("MSFT")


def test_a_failed_download_falls_back_to_the_older_answer(service, source, clock):
    service.history("AAPL", "1Y")
    clock.now += 3600
    source.error = ConnectionError("network is down")
    assert service.history("AAPL", "1Y").stale is True
    with pytest.raises(SourceFailed):
        service.history("MSFT", "1Y")
    assert service.fetches["history"]["failed"] == 2
    assert "network is down" in service.problems[0]["message"]


def test_the_ceiling_lets_a_burst_through_then_makes_callers_wait(clock):
    pacer = Pacer(per_minute=60, burst=3, clock=clock, sleep=clock.sleep)      # one a second
    assert [pacer.acquire(1, max_wait=5) for _ in range(3)] == [0.0, 0.0, 0.0]
    assert pacer.acquire(1, max_wait=5) == pytest.approx(1.0)                  # waits for the next slot
    assert pacer.acquire(8, max_wait=5) is None                                # too long a wait: turned away
    clock.now += 60
    assert pacer.acquire(3, max_wait=5) == 0.0                                 # refilled, but never past the burst
    assert pacer.acquire(1, max_wait=5) == pytest.approx(1.0)


def test_a_full_queue_turns_visitors_away_without_asking_the_source(source, clock):
    limited = DataService(source, per_minute=60, burst=2, max_wait=1, clock=clock, sleep=clock.sleep)
    limited.quotes(["AAPL", "MSFT"])                 # uses the whole burst
    with pytest.raises(SourceBusy):
        limited.details("AAPL")                      # costs 2: a two-second wait, more than allowed
    assert source.calls["details"] == []
    assert limited.ceiling["turned_away"] == 1
    clock.now += 5
    assert limited.details("AAPL").value["symbol"] == "AAPL"


# --- visitors and what they type --------------------------------------------------------------------
def test_each_visitor_has_a_request_limit(clock):
    limiter = VisitorLimiter(per_minute=60, burst=3, clock=clock)
    assert [limiter.allow("1.1.1.1")[0] for _ in range(4)] == [True, True, True, False]
    assert limiter.allow("1.1.1.1") == (False, 1)
    assert limiter.allow("2.2.2.2") == (True, 0)     # someone else is not affected
    clock.now += 2
    assert limiter.allow("1.1.1.1")[0] is True
    assert limiter.status()["limited"] == 2
    clock.now += 11 * 60                             # quiet for ten minutes: addresses are forgotten
    limiter.allow("3.3.3.3")
    assert limiter.status()["addresses_last_10_minutes"] == 1


def test_ticker_input_is_checked():
    assert clean_symbol(" aapl ") == "AAPL"
    assert clean_symbol("brk-b") == "BRK-B" and clean_symbol("^gspc") == "^GSPC" and clean_symbol("gc=f") == "GC=F"
    for bad in ("", "AAPL;DROP", "A B", "../etc", "ABCDEFGHIJKLM", "<b>", "AA\nPL", "ÄAPL"):
        with pytest.raises(BadRequest):
            clean_symbol(bad)
    assert clean_symbols("aapl, msft,AAPL") == ["AAPL", "MSFT"]
    with pytest.raises(BadRequest):
        clean_symbols(",".join(f"A{i}" for i in range(26)))
    with pytest.raises(BadRequest):
        clean_symbols(" , ")
    assert clean_range("1y") == "1Y"
    with pytest.raises(BadRequest):
        clean_range("3W")
    assert clean_query("  procter   & gamble ") == "procter & gamble"
    for bad in ("", "<script>", "x" * 41, "a/b"):
        with pytest.raises(BadRequest):
            clean_query(bad)


# --- the answers the pages get ------------------------------------------------------------------------
def test_health_answers_without_touching_the_source(client, source):
    body = client.get("/api/health").json()
    assert body["status"] == "ok" and body["app"] == "Insight by Milton"
    assert client.head("/api/health").status_code == 200
    assert all(calls == [] for calls in source.calls.values())


def test_snapshot_has_the_brief_and_all_eight_cards(client, source):
    response = client.get("/api/snapshot")
    body = response.json()
    assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
    assert [card["label"] for card in body["cards"]] == [label for label, _, _ in core.SNAPSHOT]
    assert body["cards"][0] == {"label": "S&P 500", "symbol": "^GSPC", "kind": "index", "last": 100.0,
                                "prev": 98.0, "change": 2.0, "pct": 2.0408, "high": 101.0, "low": 99.0,
                                "volume": 1_000_000.0, "spark": [97.0, 98.0, 100.0]}
    assert body["brief"].startswith("The S&P 500 rose 2.04%") and "Bitcoin trades near $100" in body["brief"]
    assert body["market"]["text"].startswith("U.S. markets")
    assert body["refresh_seconds"] in (60, 900) and body["stale"] is False and body["source"] == "Test data"
    client.get("/api/snapshot")
    assert len(source.calls["quotes"]) == 1          # the second visitor was answered from memory


def test_snapshot_with_nothing_to_show_asks_the_page_back_soon(client, source):
    source.known.clear()                             # the source answers, but has no prices at all
    body = client.get("/api/snapshot").json()
    assert all(card["last"] is None for card in body["cards"]) and len(body["cards"]) == 8
    assert body["brief"] == "Market data is unavailable right now." and body["refresh_seconds"] == 150


def test_quotes_lists_what_it_could_not_price(client):
    body = client.get("/api/quotes", params={"symbols": "aapl,nope"}).json()
    assert list(body["quotes"]) == ["AAPL"] and body["missing"] == ["NOPE"]
    assert client.get("/api/quotes").status_code == 400
    assert client.get("/api/quotes", params={"symbols": "AAPL;rm"}).status_code == 400


def test_numbers_that_are_not_numbers_become_null(client, source):
    source.volume = math.nan
    body = client.get("/api/quotes", params={"symbols": "AAPL"}).json()
    assert body["quotes"]["AAPL"]["volume"] is None


def test_history_by_range(client):
    body = client.get("/api/history/aapl", params={"range": "6m"}).json()
    assert body["symbol"] == "AAPL" and body["range"] == "6M" and body["words"] == "past 6 months"
    assert body["interval"] == "1d" and body["close"] == [1.2, 2.2, 3.2] and body["ma50"] == [None, None, 2.2]
    assert client.get("/api/history/AAPL", params={"range": "3W"}).status_code == 400
    missing = client.get("/api/history/NOPE")
    assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found"
    assert client.get("/api/history/%5EGSPC", params={"range": "1D"}).json()["interval"] == "5m"


def test_stock_details_with_ratings_and_earnings(client):
    body = client.get("/api/stock/aapl").json()
    assert body["name"] == "Apple Inc." and body["type"] == "EQUITY" and body["sector"] == "Technology"
    assert body["price"] == {"last": 200.0, "prev": 196.0, "change": 4.0, "pct": 2.0408}
    statistics = {row["label"]: row["value"] for row in body["statistics"]}
    assert statistics["Market cap"] == "3.00T" and statistics["52-week range"] == "150.00 – 210.00"
    assert "Dividend yield" not in statistics        # nothing to show, so the row is left out

    ratings = {m["name"]: (m["rating"], m["value"]) for g in body["fundamentals"]["groups"] for m in g["metrics"]}
    assert ratings["P/E (TTM)"] == ("weak", "30.0")              # above 25
    assert ratings["Forward P/E"] == ("good", "14.0")            # below 15
    assert ratings["Debt / Equity"] == ("fair", "0.80")          # Yahoo's 80 means 0.8
    assert ratings["Payout ratio"] == (None, "No dividend")
    assert body["fundamentals"]["counts"] == {"good": 4, "fair": 2, "weak": 1}
    assert [g["name"] for g in body["fundamentals"]["groups"]] == [name for name, _ in core.FUNDAMENTALS]

    last = body["earnings"]["last"]
    assert last["word"] == "Beat" and last["rating"] == "good" and last["reaction"]["pct"] == -1.9
    assert last["summary"].startswith("Apple beat expectations for the quarter ended September 30")
    assert body["earnings"]["beats"] == 2 and len(body["earnings"]["record"]) == 2
    assert body["earnings"]["next"]["estimate"] == 2.91


def test_funds_have_no_ratings_or_earnings(client, source):
    body = client.get("/api/stock/SPY").json()
    assert body["type"] == "ETF" and body["fundamentals"] is None and body["earnings"] is None
    assert source.calls["earnings"] == []            # not even asked for
    assert client.get("/api/stock/NOPE").status_code == 404
    assert client.get("/api/stock/A%20B").status_code == 400


def test_stock_page_survives_missing_earnings(client, source):
    source.earnings = lambda symbol: (_ for _ in ()).throw(ConnectionError("down"))
    body = client.get("/api/stock/AAPL").json()
    assert body["name"] == "Apple Inc." and body["earnings"] is None


def test_search(client):
    body = client.get("/api/search", params={"q": "Apple"}).json()
    assert body["results"][0]["symbol"] == "AAPL"
    assert client.get("/api/search", params={"q": "zzzz"}).json()["results"] == []
    assert client.get("/api/search", params={"q": "<script>"}).status_code == 400


def test_status_counts_what_happened(client, source):
    client.get("/api/snapshot")
    client.get("/api/snapshot")
    client.get("/api/history/NOPE")
    source.error = RuntimeError("Too Many Requests")
    client.get("/api/stock/AAPL")
    source.error = ConnectionError("down")
    client.get("/api/search", params={"q": "apple"})
    body = client.get("/api/status").json()
    assert body["totals"] == {"ok": 1, "empty": 1, "failed": 1, "rate_limited": 1}
    assert body["fetches"]["quotes"]["ok"] == 1 and body["fetches"]["history"]["empty"] == 1
    assert body["cache"]["fresh"] == 8 and body["cache"]["fetched"] == 9
    assert [p["outcome"] for p in body["problems"]] == ["failed", "rate_limited"]
    assert body["visitors"]["addresses_last_10_minutes"] == 1 and body["source"] == "Test data"


def test_a_busy_source_is_reported_politely(client, source, clock):
    client.get("/api/snapshot")
    clock.now += 600
    source.backoff = 240
    stale = client.get("/api/snapshot").json()       # older numbers, clearly labelled
    assert stale["stale"] is True and "about 4 minutes" in stale["notice"]
    busy = client.get("/api/stock/AAPL")             # nothing to fall back on
    assert busy.status_code == 503 and busy.headers["retry-after"] == "240"
    assert busy.json()["error"]["code"] == "source_busy"


def test_the_visitor_limit_applies_to_the_api_only(source, clock):
    client = make_client(source, clock, visitor_per_minute=60, visitor_burst=3)
    assert [client.get("/api/search", params={"q": "apple"}).status_code for _ in range(4)] == [200, 200, 200, 429]
    refused = client.get("/api/snapshot")
    assert refused.status_code == 429 and int(refused.headers["retry-after"]) >= 1
    assert refused.json()["error"]["code"] == "too_many_requests"
    assert client.get("/api/health").status_code == 200 and client.get("/").status_code == 200
    clock.now += 5
    assert client.get("/api/snapshot").status_code == 200


def test_behind_a_proxy_visitors_are_told_apart(source, clock):
    client = make_client(source, clock, visitor_per_minute=60, visitor_burst=1, visitor_address="forwarded")
    first = {"X-Forwarded-For": "203.0.113.5, 10.0.0.1"}
    assert client.get("/api/search", params={"q": "apple"}, headers=first).status_code == 200
    assert client.get("/api/search", params={"q": "apple"}, headers=first).status_code == 429
    other = {"X-Forwarded-For": "198.51.100.7, 10.0.0.1"}
    assert client.get("/api/search", params={"q": "apple"}, headers=other).status_code == 200
    assert client.get("/api/status", headers={"X-Forwarded-For": "192.0.2.1, 10.0.0.1"}).json()[
        "visitors"]["forwarding_steps_on_this_request"] == 2


def test_pages_and_theme_are_served(client):
    home = client.get("/")
    assert home.status_code == 200 and "Market Snapshot" in home.text and "Today's brief" in home.text
    assert "default-src 'self'" in home.headers["content-security-policy"]
    assert client.head("/").status_code == 200
    assert "Fetches from the data source" in client.get("/status").text
    theme = client.get("/theme.css").text
    assert "--bg: #FDFBF7;" in theme and "--accent: #D47A5D;" in theme       # Milton cream and terracotta
    assert "--bg: #161513;" in theme and 'data-theme="dark"' in theme
    for path in ("/static/style.css", "/static/home.js", "/static/theme.js", "/static/status.js",
                 "/assets/logo.png", "/assets/logo-dark.png", "/favicon.ico"):
        assert client.get(path).status_code == 200, path
    assert client.get("/static/../app.py").status_code == 404
    assert client.get("/docs").status_code == 404


# --- the Yahoo adapter, without Yahoo -----------------------------------------------------------------
def test_yahoo_answers_are_turned_into_plain_data(monkeypatch):
    pd = pytest.importorskip("pandas")
    from web.yahoo import YahooSource
    index = pd.date_range("2026-11-02", periods=3, freq="D", tz="America/New_York")
    frame = pd.DataFrame({"Open": [1.0, 2.0, 3.0], "High": [1.5, 2.5, 3.5], "Low": [0.5, 1.5, 2.5],
                          "Close": [1.23456789, 2.0, 3.0], "Volume": [10, 20, 30],
                          "MA50": [math.nan, 2.0, 2.5], "MA200": [math.nan] * 3}, index=index)
    monkeypatch.setattr(core, "fetch_history", lambda symbol, range_key: frame)
    bars = YahooSource().history("AAPL", "1Y")
    assert bars["interval"] == "1d" and bars["t"][0] == int(index[0].timestamp())
    assert bars["close"] == [1.2346, 2.0, 3.0] and bars["ma50"] == [None, 2.0, 2.5] and bars["ma200"] == [None] * 3
    monkeypatch.setattr(core, "fetch_history", lambda symbol, range_key: frame.iloc[0:0])
    assert YahooSource().history("NOPE", "1Y") is None

    raw = dict(APPLE, companyOfficers=[{"name": "Someone"}], beta=math.nan, somethingElse="x")
    monkeypatch.setattr(core, "fetch_info", lambda symbol: raw)
    facts = YahooSource().details("AAPL")
    assert set(facts) <= set(DETAIL_FIELDS) and "beta" not in facts and facts["trailingPE"] == 30.0
    monkeypatch.setattr(core, "fetch_info", lambda symbol: {"quoteType": "EQUITY", "regularMarketPrice": 5.0})
    assert YahooSource().details("AAPL")["partial"] is True      # no sector, no margins: cut short
    monkeypatch.setattr(core, "fetch_info", lambda symbol: {"trailingPegRatio": None})
    assert YahooSource().details("NOPE") is None


def test_yahoo_rate_limits_are_recognised(monkeypatch):
    from web.yahoo import YahooSource
    monkeypatch.setattr(core, "_BACKOFF", {"until": 0.0, "strikes": 0, "last": 0.0})
    yahoo = YahooSource()
    assert yahoo.backoff_seconds() == 0
    assert yahoo.is_rate_limit(ConnectionError("network is down")) is False
    assert yahoo.is_rate_limit(RuntimeError("Too Many Requests. Rate limited. Try after a while.")) is True
    assert 170 <= yahoo.backoff_seconds() <= 260     # about three minutes, stretched by up to 40 %


def test_trim_cache_drops_the_oldest(monkeypatch):
    monkeypatch.setattr(core, "_CACHE", {("quote", f"S{i}"): (float(i), {}) for i in range(10)})
    assert core.trim_cache(4) == 6
    assert sorted(key[1] for key in core._CACHE) == ["S6", "S7", "S8", "S9"]


def test_trim_cache_also_limits_how_much_the_price_tables_hold(monkeypatch):
    class Table:
        size = 1000                                  # like a pandas table: rows x columns

    cache = {("history", f"S{i}"): (float(i), Table()) for i in range(6)}
    cache[("quote", "AAPL")] = (0.5, {"last": 1.0})  # small things have no size and are not counted
    monkeypatch.setattr(core, "_CACHE", cache)
    assert core.trim_cache(100, max_cells=2500) == 4
    assert sorted(key[1] for key in core._CACHE) == ["AAPL", "S4", "S5"]


@pytest.mark.skipif(os.environ.get("INSIGHT_LIVE_TEST") != "1", reason="set INSIGHT_LIVE_TEST=1 to contact Yahoo")
def test_live_snapshot_from_yahoo():
    from web.yahoo import YahooSource
    body = TestClient(create_app(source=YahooSource(), settings=Settings())).get("/api/snapshot").json()
    assert body["cards"][0]["symbol"] == "^GSPC" and body["cards"][0]["last"] > 0
