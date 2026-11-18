"""Every number that can be tuned without touching the code, read from environment variables.

The defaults are starting guesses for one classroom. The status page (/status) shows whether they are
too tight or too loose on the real host.
"""

import os
from dataclasses import dataclass


def _number(name, default):
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return float(default)


@dataclass
class Settings:
    # Ceiling on how fast the data source is asked. One unit is roughly one request to Yahoo:
    # a quote costs 1 per symbol, a chart 1, company details 2, earnings 3, a search 1.
    source_per_minute: float = 120      # steady pace
    source_burst: float = 30            # how many can go at once after a quiet spell
    source_max_wait: float = 8          # seconds a visitor may wait for a turn before being told "busy"

    # Request limit for each visitor address (applies to /api/ only). A classroom usually shares one
    # address, so this is sized for a room, not a person.
    visitor_per_minute: float = 600
    visitor_burst: float = 120
    visitor_address: str = "socket"     # "socket", or "forwarded" behind a host's proxy (X-Forwarded-For)

    cache_entries: int = 2000           # answers kept in memory before the oldest are dropped
    cache_numbers: int = 1_500_000      # ...or the numbers inside them (charts are big), about 50 MB

    @classmethod
    def from_env(cls):
        address = os.environ.get("INSIGHT_VISITOR_ADDRESS", "socket").strip().lower()
        return cls(
            source_per_minute=_number("INSIGHT_SOURCE_PER_MINUTE", cls.source_per_minute),
            source_burst=_number("INSIGHT_SOURCE_BURST", cls.source_burst),
            source_max_wait=_number("INSIGHT_SOURCE_MAX_WAIT", cls.source_max_wait),
            visitor_per_minute=_number("INSIGHT_VISITOR_PER_MINUTE", cls.visitor_per_minute),
            visitor_burst=_number("INSIGHT_VISITOR_BURST", cls.visitor_burst),
            visitor_address=address if address in ("socket", "forwarded") else "socket",
            cache_entries=int(_number("INSIGHT_CACHE_ENTRIES", cls.cache_entries)),
            cache_numbers=int(_number("INSIGHT_CACHE_NUMBERS", cls.cache_numbers)),
        )
