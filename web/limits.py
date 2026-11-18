"""Protecting the server: a request limit for each visitor, and checks on what visitors type."""

import re
import threading
import time

import insight_core as core

MAX_SYMBOLS = 25                # symbols in one /api/quotes request
SEARCH_RE = re.compile(r"[\w .&'\-^=]{1,40}")
QUIET_AFTER = 10 * 60           # seconds after which a visitor's address is forgotten


class BadRequest(ValueError):
    """What the visitor sent can't be used. The message is shown to them."""


class NotFound(LookupError):
    """Nothing is known under that name. The message is shown to the visitor."""


def clean_symbol(text):
    """ "aapl " -> "AAPL". Anything that couldn't be a ticker is refused before the source is asked."""
    symbol = (text or "").strip().upper()
    if not core.TICKER_RE.fullmatch(symbol):
        raise BadRequest("That doesn't look like a ticker symbol. Use up to 12 letters, digits or . - ^ = "
                         "(for example AAPL, BRK-B or ^GSPC).")
    return symbol


def clean_symbols(text):
    parts = [part for part in (text or "").split(",") if part.strip()]
    if not parts:
        raise BadRequest("Add at least one symbol, for example ?symbols=AAPL,MSFT.")
    if len(parts) > MAX_SYMBOLS:
        raise BadRequest(f"That's too many symbols at once. The most is {MAX_SYMBOLS}.")
    return list(dict.fromkeys(clean_symbol(part) for part in parts))


def clean_range(text):
    key = (text or "").strip().upper()
    if key not in core.RANGES:
        raise BadRequest("Unknown range. Use one of " + ", ".join(core.RANGES) + ".")
    return key


def clean_query(text):
    query = " ".join((text or "").split())
    if not SEARCH_RE.fullmatch(query):
        raise BadRequest("Search for a company name or ticker, up to 40 letters and digits.")
    return query


class VisitorLimiter:
    """At most `per_minute` requests a minute from one address, with `burst` allowed at once.
    Addresses are kept in memory only, and forgotten after ten quiet minutes."""

    def __init__(self, per_minute, burst, clock=time.time, max_visitors=50_000):
        self.rate = per_minute / 60.0
        self.burst = max(float(burst), 1.0)
        self.clock, self.max_visitors = clock, max_visitors
        self._buckets = {}          # address -> [tokens, last seen]
        self._lock = threading.Lock()
        self._tidied = clock()
        self.limited = 0

    def allow(self, address):
        """(True, 0) or (False, seconds until the next request will be let through)."""
        if self.rate <= 0:
            return True, 0
        with self._lock:
            now = self.clock()
            if now - self._tidied > 60 or len(self._buckets) > self.max_visitors:
                self._tidy(now)
            bucket = self._buckets.get(address)
            if bucket is None:
                bucket = self._buckets[address] = [self.burst, now]
            bucket[0] = min(self.burst, bucket[0] + (now - bucket[1]) * self.rate)
            bucket[1] = now
            if bucket[0] >= 1:
                bucket[0] -= 1
                return True, 0
            self.limited += 1
            return False, max(1, round((1 - bucket[0]) / self.rate))

    def _tidy(self, now):
        self._tidied = now
        for address in [a for a, (_, seen) in self._buckets.items() if now - seen > QUIET_AFTER]:
            del self._buckets[address]
        if len(self._buckets) > self.max_visitors:      # a flood of made-up addresses: start over
            self._buckets.clear()

    def status(self):
        with self._lock:
            now = self.clock()
            recent = sum(1 for _, seen in self._buckets.values() if now - seen <= QUIET_AFTER)
            return {"addresses_last_10_minutes": recent, "limited": self.limited,
                    "per_minute": round(self.rate * 60), "burst": round(self.burst)}
