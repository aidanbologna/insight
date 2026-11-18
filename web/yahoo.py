"""Yahoo Finance as a MarketSource, using the same functions the Windows app uses (insight_core)."""

import math

import insight_core as core

from .source import DETAIL_FIELDS, MarketSource


def _number(value, digits=4):
    """A float safe to send as JSON: rounded, with "not a number" turned into None."""
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return round(value, digits) if math.isfinite(value) else None


class YahooSource(MarketSource):
    name = "Yahoo Finance"

    def __init__(self, keep=600, keep_cells=4_000_000):
        # insight_core remembers every download and has no limit of its own. Hold on to at most this
        # many, and to price tables adding up to this many numbers (about 32 MB).
        self.keep, self.keep_cells = keep, keep_cells

    def _tidy(self):
        core.trim_cache(self.keep, self.keep_cells)

    def quotes(self, symbols):
        try:
            return core.fetch_quotes(list(symbols))
        finally:
            self._tidy()

    def history(self, symbol, range_key):
        try:
            hist = core.fetch_history(symbol, range_key)
        finally:
            self._tidy()
        if hist.empty:
            return None
        interval = core.RANGES[range_key][1]
        bars = {"interval": interval, "t": [int(stamp.timestamp()) for stamp in hist.index]}
        for column in ("Open", "High", "Low", "Close", "Volume", "MA50", "MA200"):
            if column in hist.columns:
                digits = 0 if column == "Volume" else 4
                bars[column.lower()] = [_number(v, digits) for v in hist[column].tolist()]
        return bars

    def details(self, symbol):
        try:
            info = core.fetch_info(symbol)
        finally:
            self._tidy()
        kind = info.get("quoteType")
        if not kind and core.is_missing(info.get("regularMarketPrice")):
            return None         # Yahoo knows neither what it is nor what it costs: not a real symbol
        facts = {}
        for field in DETAIL_FIELDS:
            value = info.get(field)
            if isinstance(value, bool) or core.is_missing(value):
                continue
            if isinstance(value, (int, float)):
                value = value if math.isfinite(value) else None
            elif not isinstance(value, str):
                continue
            if value is not None:
                facts[field] = value
        facts.setdefault("symbol", symbol)
        # the same test insight_core uses before it keeps an answer: after a rejected session Yahoo
        # quietly sends a cut-down record with no sector and no margins
        if not kind or (kind == "EQUITY" and "sector" not in info and "profitMargins" not in info):
            facts["partial"] = True
        return facts

    def earnings(self, symbol):
        try:
            return core.fetch_earnings(symbol)
        finally:
            self._tidy()

    def search(self, query):
        return core.search_symbols(query)

    def backoff_seconds(self):
        return core.rate_limited()

    def is_rate_limit(self, error):
        return isinstance(error, core.YahooBusy) or core.note_rate_limit(error)
