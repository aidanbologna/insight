"""One cache for everyone, in front of the data source.

When thirty students open the same stock, the source is asked once and everyone is answered from
memory. This module also
  - joins visitors who ask for the same thing at the same moment onto one download,
  - keeps a ceiling on how fast the source is asked,
  - stops asking while the source says "too many requests", serving what it already has,
  - and counts what happened, for the status page.

Nothing here knows about Yahoo: it works with any MarketSource.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

import insight_core as core

from .source import SourceBusy, SourceFailed

log = logging.getLogger("insight.web")

# How long an answer counts as fresh. These are the lifetimes the Windows app uses.
QUOTE_TTL = core.QUOTE_TTL          # 55 seconds
HISTORY_TTL_DAILY = 15 * 60
HISTORY_TTL_INTRADAY = 60
DETAILS_TTL = 5 * 60
EARNINGS_TTL = 6 * 3600
SEARCH_TTL = 10 * 60
PARTIAL_TTL = 20                    # a cut-short answer is asked for again soon
UNKNOWN_TTL = 2 * 60                # "no such symbol" is remembered briefly, so typos don't hammer the source

# What one fetch costs against the ceiling, in rough requests to the source.
COST = {"quotes": 1, "history": 1, "details": 2, "earnings": 3, "search": 1}
KINDS = tuple(COST)
OUTCOMES = ("ok", "empty", "failed", "rate_limited")
JOIN_WAIT = 25                      # seconds a visitor waits for someone else's download of the same thing


class Answer:
    """What the cache hands back: the value (None = the source has nothing for this), when it was
    fetched, and whether it is older than its lifetime."""
    __slots__ = ("value", "fetched", "stale")

    def __init__(self, value, fetched, stale=False):
        self.value, self.fetched, self.stale = value, fetched, stale


class _Entry:
    __slots__ = ("value", "fetched", "ttl", "weight")

    def __init__(self, value, fetched, ttl):
        self.value, self.fetched, self.ttl, self.weight = value, fetched, ttl, _weight(value)


def _weight(value):
    """Roughly how many numbers an answer holds, so a five-year chart counts for more than a price."""
    if isinstance(value, dict):
        return 1 + sum(len(v) for v in value.values() if isinstance(v, list))
    if isinstance(value, list):
        return 1 + len(value)
    return 1


class Pacer:
    """A ceiling on how fast the source is asked: `per_minute` on average, `burst` at once.
    Callers wait their turn; if the wait would be longer than they can afford they are turned away."""

    def __init__(self, per_minute, burst, clock=time.time, sleep=time.sleep):
        self.rate = per_minute / 60.0
        self.burst = max(float(burst), 1.0)
        self.clock, self.sleep = clock, sleep
        self.tokens, self.updated = self.burst, clock()
        self._lock = threading.Lock()

    def acquire(self, cost, max_wait):
        """Seconds waited, or None when the queue is too long to join."""
        if self.rate <= 0:
            return 0.0
        with self._lock:
            now = self.clock()
            self.tokens = min(self.burst, self.tokens + (now - self.updated) * self.rate)
            self.updated = now
            wait = max(0.0, (cost - self.tokens) / self.rate)
            if wait > max_wait:
                return None
            self.tokens -= cost         # may go below zero: that is the queue
        if wait:
            self.sleep(wait)
        return wait


class DataService:
    def __init__(self, source, per_minute=120, burst=30, max_wait=8.0, max_entries=2000, max_numbers=1_500_000,
                 clock=time.time, sleep=time.sleep):
        self.source = source
        self.clock = clock
        self.max_wait, self.max_entries, self.max_numbers = max_wait, max_entries, max_numbers
        self._numbers = 0               # the weight of everything in memory (see _weight)
        self.pacer = Pacer(per_minute, burst, clock, sleep)
        self.started = clock()
        self._lock = threading.Lock()
        self._entries = {}              # (kind, key) -> _Entry
        self._flights = {}              # (kind, key) -> threading.Event, set when that download lands
        self.fetches = {kind: dict.fromkeys(OUTCOMES, 0) for kind in KINDS}
        self.last_ok = dict.fromkeys(KINDS)
        self.cache = {"fresh": 0, "fetched": 0, "joined": 0, "stale": 0}
        self.ceiling = {"waited": 0, "turned_away": 0, "held_back": 0}
        self.problems = deque(maxlen=25)

    # --- the five kinds of answer ---------------------------------------------------------------
    def quotes(self, symbols):
        """({symbol: Answer} for the symbols that have a price, [symbols without one])."""
        answers = self._get_many("quotes", list(symbols), lambda found: QUOTE_TTL, self.source.quotes)
        priced = {sym: a for sym, a in answers.items() if a.value is not None}
        return priced, [sym for sym in dict.fromkeys(symbols) if sym not in priced]

    def history(self, symbol, range_key):
        ttl = HISTORY_TTL_DAILY if core.RANGES[range_key][1] == "1d" else HISTORY_TTL_INTRADAY
        return self._get("history", (symbol, range_key), lambda found: ttl,
                         lambda: self.source.history(symbol, range_key))

    def details(self, symbol):
        return self._get("details", symbol, lambda found: PARTIAL_TTL if found.get("partial") else DETAILS_TTL,
                         lambda: self.source.details(symbol))

    def earnings(self, symbol):
        return self._get("earnings", symbol, lambda found: EARNINGS_TTL, lambda: self.source.earnings(symbol))

    def search(self, query):
        return self._get("search", query.lower(), lambda found: SEARCH_TTL,
                         lambda: self.source.search(query) or None)

    def notice(self):
        """A sentence for the page when it is being shown older numbers."""
        holding = self.source.backoff_seconds()
        if holding > 0:
            return self._busy_text(holding)
        return f"Couldn't reach {self.source.name} just now, so these are the latest numbers this site has."

    # --- the cache ----------------------------------------------------------------------------------
    def _get(self, kind, key, ttl, fetch):
        def fetch_one(keys):
            value = fetch()
            return {} if value is None else {key: value}
        return self._get_many(kind, [key], ttl, fetch_one)[key]

    def _get_many(self, kind, keys, ttl, fetch_many):
        """An Answer for every key. Fresh ones come from memory; the rest are fetched in one call,
        unless someone else is already fetching them or the source has asked to be left alone."""
        keys = list(dict.fromkeys(keys))
        answers, mine, theirs, held = {}, [], {}, []
        holding = self.source.backoff_seconds()
        with self._lock:
            now = self.clock()
            for key in keys:
                entry = self._entries.get((kind, key))
                if entry and now - entry.fetched < entry.ttl:
                    self.cache["fresh"] += 1
                    answers[key] = Answer(entry.value, entry.fetched)
                elif (kind, key) in self._flights:
                    theirs[key] = self._flights[(kind, key)]
                elif holding > 0:
                    held.append(key)
                else:
                    mine.append(key)
                    self._flights[(kind, key)] = threading.Event()

        problem = self._fetch(kind, mine, ttl, fetch_many) if mine else None
        for landed in theirs.values():
            landed.wait(JOIN_WAIT)

        with self._lock:        # whatever is in memory now is the answer, even if it is an older one
            now = self.clock()
            self.ceiling["held_back"] += len(held)
            for key in mine + list(theirs) + held:
                entry = self._entries.get((kind, key))
                if entry is not None:
                    stale = now - entry.fetched >= entry.ttl
                    self.cache["stale" if stale else "joined" if key in theirs else "fetched"] += 1
                    answers[key] = Answer(entry.value, entry.fetched, stale)

        missing = [key for key in keys if key not in answers]
        if missing:
            if problem is None:     # held back, or someone else's download failed or didn't land in time
                holding = self.source.backoff_seconds()
                problem = (SourceBusy(self._busy_text(holding), holding) if holding > 0 else
                           SourceFailed(f"{self.source.name} didn't answer in time. Please try again."))
            if len(missing) == len(keys):
                raise problem       # nothing at all to show
            for key in missing:     # part of a batch: the rest is still worth showing
                answers[key] = Answer(None, self.clock(), stale=True)
        return answers

    def _fetch(self, kind, keys, ttl, fetch_many):
        """Ask the source for these keys, store what comes back and count how it went.
        Returns the problem to tell anyone left without an answer (None when the source answered)."""
        found, outcome, problem, holding = {}, None, None, 0.0
        try:
            waited = self.pacer.acquire(COST[kind] * len(keys), self.max_wait)
            if waited is None:      # the source is never asked, so there is no outcome to count
                with self._lock:
                    self.ceiling["turned_away"] += 1
                return SourceBusy("A lot of people are looking things up right now. "
                                  "Please try again in a few seconds.", 5)
            if waited:
                with self._lock:
                    self.ceiling["waited"] += 1
            error = None
            try:
                found = fetch_many(keys) or {}
                outcome = "ok" if found else "empty"
            except Exception as exc:
                error = exc
                limited = isinstance(exc, SourceBusy) or self.source.is_rate_limit(exc)
                outcome = "rate_limited" if limited else "failed"
            holding = self.source.backoff_seconds()
            if outcome == "empty" and holding > 0:
                outcome = "rate_limited"        # it answered nothing because it is turning us away
            if outcome == "rate_limited":
                problem = SourceBusy(self._busy_text(holding or 60), holding or 60)
            elif outcome == "failed":
                problem = SourceFailed(f"Couldn't reach {self.source.name}. Please try again shortly.")
            if problem:
                self._note_problem(kind, keys, outcome, error or problem)
            return problem
        finally:
            with self._lock:
                landed = [self._flights.pop((kind, key)) for key in keys]
                try:
                    now = self.clock()
                    if outcome:
                        self.fetches[kind][outcome] += 1
                        if outcome == "ok":
                            self.last_ok[kind] = now
                    answered = outcome in ("ok", "empty") and holding <= 0
                    for key in keys:
                        if key in found:
                            self._store((kind, key), _Entry(found[key], now, ttl(found[key])))
                        elif answered and (kind, key) not in self._entries:
                            # the source has nothing for this key. (An older real answer is kept
                            # instead, in case this was a hiccup.)
                            self._store((kind, key), _Entry(None, now, UNKNOWN_TTL))
                    self._trim()
                finally:
                    for event in landed:
                        event.set()

    def _store(self, key, entry):
        old = self._entries.get(key)
        self._numbers += entry.weight - (old.weight if old else 0)
        self._entries[key] = entry

    def _trim(self):
        """Drop the oldest answers once there are too many, or once they hold too many numbers.
        A tenth more than needed goes each time, so this isn't repeated on every fetch."""
        if len(self._entries) <= self.max_entries and self._numbers <= self.max_numbers:
            return
        for key in sorted(self._entries, key=lambda k: self._entries[k].fetched):
            if len(self._entries) <= self.max_entries * 0.9 and self._numbers <= self.max_numbers * 0.9:
                break
            self._numbers -= self._entries.pop(key).weight

    def _busy_text(self, seconds):
        minutes = max(1, round(seconds / 60))
        return (f"{self.source.name} has asked this site to slow down. "
                f"New numbers should be back in about {minutes} minute{'s' if minutes != 1 else ''}.")

    def _note_problem(self, kind, keys, outcome, error):
        what = ", ".join(" ".join(k) if isinstance(k, tuple) else str(k) for k in keys[:6])
        text = f"{type(error).__name__}: {error}"[:300]
        log.warning("fetch %s [%s] %s: %s", kind, what, outcome, text)
        with self._lock:
            self.problems.appendleft({"at": iso(self.clock()), "kind": kind, "what": what,
                                      "outcome": outcome, "message": text})

    # --- for the status page ------------------------------------------------------------------------
    def status(self):
        holding = self.source.backoff_seconds()
        with self._lock:
            return {
                "source": self.source.name,
                "started": iso(self.started),
                "uptime_seconds": int(self.clock() - self.started),
                "holding_back_seconds": int(holding),
                "fetches": {kind: dict(self.fetches[kind]) for kind in KINDS},
                "totals": {outcome: sum(self.fetches[kind][outcome] for kind in KINDS) for outcome in OUTCOMES},
                "last_ok": {kind: iso(when) if when else None for kind, when in self.last_ok.items()},
                "cache": dict(self.cache, entries=len(self._entries), numbers=self._numbers),
                "ceiling": dict(self.ceiling, per_minute=round(self.pacer.rate * 60),
                                burst=round(self.pacer.burst)),
                "problems": list(self.problems),
            }


def iso(seconds):
    return datetime.fromtimestamp(seconds, timezone.utc).isoformat(timespec="seconds")
