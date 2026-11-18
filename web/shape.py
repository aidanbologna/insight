"""Turns what the data source returned into the plain data the pages receive.

The wording and the rules (today's brief, key statistics, fundamentals ratings, the earnings summary)
all come from insight_core, so the web pages say exactly what the Windows app says.
"""

import math
from datetime import date, datetime

import insight_core as core

from .service import iso


def plain(value):
    """Make a value safe to send as JSON: dates become text, "not a number" becomes null."""
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(v) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, (str, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    try:                                    # numpy numbers and anything else number-like
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return str(value)


def freshness(service, answers, as_of=None):
    """The "how old is this" part of every answer: when it was fetched, and a sentence if it's old."""
    answers = list(answers)
    stale = any(a.stale for a in answers)
    if as_of is None:
        as_of = min((a.fetched for a in answers), default=service.clock())
    return {"as_of": iso(as_of), "stale": stale, "notice": service.notice() if stale else None,
            "source": service.source.name}


def quote(q):
    return {"last": round(q["last"], 4), "prev": round(q["prev"], 4), "change": round(q["change"], 4),
            "pct": round(q["pct"], 4), "high": round(q["high"], 4), "low": round(q["low"], 4),
            "volume": q["volume"], "spark": [round(v, 4) for v in q["spark"]]}


def snapshot(service, priced):
    """The Home page: today's date, whether the market is open, the brief and the eight cards."""
    quotes = {sym: a.value for sym, a in priced.items()}
    is_open, text = core.market_status()
    cards = []
    for label, symbol, kind in core.SNAPSHOT:
        q = quotes.get(symbol)
        cards.append({"label": label, "symbol": symbol, "kind": kind, **(quote(q) if q else {"last": None})})
    if quotes:      # the Windows app refreshes Home every minute, and slows right down while the market is closed
        refresh = 60 if is_open else core.CLOSED_MARKET_MINUTES * 60
    else:           # nothing to show at all: look again soon, whatever the hour
        refresh = 150
    return plain({
        "date": core.now_eastern().strftime("%A, %B %d").replace(" 0", " "),
        "market": {"open": is_open, "text": text},
        "brief": core.compose_brief(quotes),
        "cards": cards,
        "refresh_seconds": refresh,
        **freshness(service, priced.values()),
    })


def quotes(service, priced, missing):
    return plain({"quotes": {sym: quote(a.value) for sym, a in priced.items()}, "missing": missing,
                  **freshness(service, priced.values())})


def history(service, symbol, range_key, answer):
    return plain({"symbol": symbol, "range": range_key, "words": core.RANGE_WORDS[range_key], **answer.value,
                  **freshness(service, [answer])})


def search(service, query, answer):
    return plain({"query": query, "results": answer.value or [], **freshness(service, [answer])})


def key_statistics(info):
    """The rows of the Windows app's "Key Statistics" box."""
    def span(low, high):
        if core.is_missing(low) or core.is_missing(high):
            return None
        return f"{core.fmt_price(low)} – {core.fmt_price(high)}"

    dividend = info.get("trailingAnnualDividendYield")
    rows = [
        ("Open", core.fmt_price(info.get("regularMarketOpen") or info.get("open"))),
        ("Previous close", core.fmt_price(info.get("regularMarketPreviousClose"))),
        ("Day range", span(info.get("regularMarketDayLow") or info.get("dayLow"),
                           info.get("regularMarketDayHigh") or info.get("dayHigh"))),
        ("52-week range", span(info.get("fiftyTwoWeekLow"), info.get("fiftyTwoWeekHigh"))),
        ("Volume", core.fmt_big(info.get("regularMarketVolume") or info.get("volume"))),
        ("Avg. volume", core.fmt_big(info.get("averageVolume"))),
        ("Market cap", core.fmt_big(info.get("marketCap"))),
        ("P/E (TTM)", core.fmt_price(info.get("trailingPE"))),
        ("Forward P/E", core.fmt_price(info.get("forwardPE"))),
        ("EPS (TTM)", core.fmt_price(info.get("trailingEps"))),
        ("Dividend yield", f"{dividend * 100:.2f}%" if dividend else None),
        ("Beta", core.fmt_price(info.get("beta"))),
        ("Sector", info.get("sector")),
        ("Industry", info.get("industry")),
    ]
    return [{"label": label, "value": value} for label, value in rows if value and value != "—"]


def fundamentals(info):
    """Every metric with its good / fair / weak rating. None for funds, indexes, crypto and futures,
    and for companies with too little to judge, exactly as the Windows app hides the section."""
    groups, counts = [], {"good": 0, "fair": 0, "weak": 0}
    for group, metrics in core.FUNDAMENTALS:
        rows = []
        for spec in metrics:
            rating, text = core.judge_metric(spec, info)
            if rating:
                counts[rating] += 1
            rows.append({"name": spec["name"], "value": text, "rating": rating, "about": spec["about"],
                         "rules": [{"rating": r, "text": rule} for r, rule in core.describe_cutoffs(spec)]})
        groups.append({"name": group, "metrics": rows})
    if info.get("quoteType") != "EQUITY" or sum(counts.values()) < 3:
        return None
    return {"counts": counts, "groups": groups}


def earnings(symbol, info, result):
    """The earnings box: last report with its plain-English summary, the record, the next date."""
    if not result or (not result.get("last") and not result.get("next")):
        return None
    shaped = {"last": None, "next": result.get("next"), "record": [], "beats": 0}
    last = result.get("last")
    if last:
        word, rating = core.beat_word(last["surprise"])
        names = core.company_names(symbol, info)
        reaction = last.get("reaction")
        shaped["last"] = {**{k: v for k, v in last.items() if k != "reaction"}, "word": word, "rating": rating,
                          "reaction": {"pct": reaction[0], "when": reaction[1]} if reaction else None,
                          "summary": core.earnings_summary(names[0] if names else symbol, last)}
    for when, surprise in result.get("record") or []:
        word, rating = core.beat_word(surprise)
        shaped["record"].append({"date": when, "surprise": surprise, "word": word, "rating": rating})
    shaped["beats"] = sum(1 for row in shaped["record"] if row["surprise"] > 1)
    return shaped


def stock(service, symbol, details, earnings_answer):
    info = details.value
    last, prev = info.get("regularMarketPrice"), info.get("regularMarketPreviousClose")
    known = not core.is_missing(last) and not core.is_missing(prev)
    answers = [details] + ([earnings_answer] if earnings_answer else [])
    return plain({
        "symbol": symbol,
        "name": core.tidy_name(info.get("shortName") or info.get("longName")) or symbol,
        "type": info.get("quoteType"),
        "exchange": info.get("fullExchangeName") or info.get("exchange"),
        "currency": info.get("currency"),
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "about": info.get("longBusinessSummary"),
        "price": {"last": last, "prev": prev, "change": round(last - prev, 4) if known else None,
                  "pct": round((last / prev - 1) * 100, 4) if known and prev else None},
        "statistics": key_statistics(info),
        "fundamentals": fundamentals(info),
        "earnings": earnings(symbol, info, earnings_answer.value) if earnings_answer else None,
        "partial": bool(info.get("partial")),
        **freshness(service, answers, as_of=details.fetched),     # the price's age, not the earnings'
    })
