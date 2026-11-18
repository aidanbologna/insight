"""The one doorway to market data.

Every price, chart and company fact the server hands out comes through a MarketSource. Today that is
Yahoo Finance (web/yahoo.py). Using another provider means writing one more class with these five
methods and passing it to create_app(); the cache, the limits and the pages don't change.

Answers are plain Python data (dicts, lists, numbers, datetimes) so nothing above this line needs to
know which library fetched them.
"""

import insight_core as core


class SourceBusy(Exception):
    """The source has asked to be left alone for a while, or its queue is full right now."""

    def __init__(self, message, retry_after):
        super().__init__(message)
        self.retry_after = max(1, int(retry_after))


class SourceFailed(Exception):
    """The source could not be reached and there is no older answer to fall back on."""


def _detail_fields():
    fields = ["symbol", "shortName", "longName", "quoteType", "exchange", "fullExchangeName", "currency",
              "sector", "industry", "longBusinessSummary", "website",
              "regularMarketPrice", "regularMarketPreviousClose", "regularMarketOpen", "open",
              "regularMarketDayLow", "dayLow", "regularMarketDayHigh", "dayHigh", "regularMarketVolume",
              "volume", "averageVolume", "fiftyTwoWeekLow", "fiftyTwoWeekHigh", "marketCap", "trailingEps",
              "forwardEps", "trailingAnnualDividendYield", "beta", "lastDividendValue"]
    for _, metrics in core.FUNDAMENTALS:
        for spec in metrics:
            keys = spec["key"] if isinstance(spec["key"], tuple) else (spec["key"],)
            fields += [k for k in (*keys, spec.get("loss_eps")) if k and k not in fields]
    return tuple(fields)


# The company facts details() may return. The names are Yahoo's, because the fundamentals rules in
# insight_core are written against them; another provider maps its own names onto these.
DETAIL_FIELDS = _detail_fields()


class MarketSource:
    name = "Unnamed source"

    def quotes(self, symbols):
        """Latest price for each symbol it knows:
        {symbol: {"last", "prev", "change", "pct", "high", "low", "volume", "spark": [recent closes]}}.
        Symbols it can't price are left out."""
        raise NotImplementedError

    def history(self, symbol, range_key):
        """Price bars for one of insight_core.RANGES, as columns:
        {"interval", "t": [unix seconds], "open", "high", "low", "close", "volume", "ma50", "ma200"}.
        None when the symbol has no prices."""
        raise NotImplementedError

    def details(self, symbol):
        """Company facts as a flat dict using DETAIL_FIELDS; None when the symbol is unknown.
        Add "partial": True when the answer came back cut short and should be asked for again soon."""
        raise NotImplementedError

    def earnings(self, symbol):
        """Last report, beat/miss record and next report date, shaped like insight_core.fetch_earnings().
        None when the symbol has no earnings (funds, indexes, crypto)."""
        raise NotImplementedError

    def search(self, query):
        """Matches for a company name or ticker, best first: [{"symbol", "name", "type", "exchange"}]."""
        raise NotImplementedError

    def backoff_seconds(self):
        """Seconds the source wants to be left alone (0 while it is answering normally)."""
        return 0.0

    def is_rate_limit(self, error):
        """True when this error is the source saying "too many requests"."""
        return False
