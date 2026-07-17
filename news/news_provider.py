"""
Headline, earnings, and fundamentals lookups via yfinance's free (no API
key) endpoints.

IMPORTANT LIMITATION: yfinance only exposes *current* news and *current*
fundamentals - there is no way to ask "what were the headlines for AAPL on
2024-03-01" for free. That means none of this module can be used inside
the historical backtest loop (backtest/engine.py); it's only meaningful
for enriching signals/order intents generated from the most recent bar,
i.e. the live/paper flow described in the README.
"""

import datetime as dt

import yfinance as yf


def get_headlines(symbol: str, limit: int = 5) -> list[dict]:
    """Returns the most recent news items for `symbol` as a list of dicts:
    {title, summary, publisher, published, url}. Best-effort: returns an
    empty list if yfinance has nothing or the lookup fails."""
    try:
        raw = yf.Ticker(symbol).news or []
    except Exception:
        return []

    headlines = []
    for item in raw[:limit]:
        content = item.get("content", {})
        headlines.append({
            "title": content.get("title", ""),
            "summary": content.get("summary") or content.get("description", ""),
            "publisher": (content.get("provider") or {}).get("displayName", ""),
            "published": content.get("pubDate", ""),
            "url": (content.get("canonicalUrl") or {}).get("url", ""),
        })
    return headlines


def get_fundamentals(symbol: str) -> dict:
    """Returns a small snapshot of fundamentals: market cap, P/E ratios,
    sector/industry, 52-week range. Best-effort: missing keys are omitted
    rather than raising, since yfinance's `info` coverage varies by ticker."""
    try:
        info = yf.Ticker(symbol).info or {}
    except Exception:
        return {}

    fields = [
        "marketCap", "trailingPE", "forwardPE", "sector", "industry",
        "fiftyTwoWeekHigh", "fiftyTwoWeekLow", "shortName",
    ]
    return {k: info[k] for k in fields if info.get(k) is not None}


def get_next_earnings_date(symbol: str) -> dt.date | None:
    """Returns the next scheduled earnings date for `symbol`, or None if
    unavailable. yfinance's calendar data can be stale for less-followed
    tickers (returning a date that's already passed), so past dates are
    treated as unknown rather than misreported as "next"."""
    try:
        calendar = yf.Ticker(symbol).calendar or {}
    except Exception:
        return None

    dates = calendar.get("Earnings Date")
    if not dates:
        return None
    next_date = dates[0]
    if next_date < dt.date.today():
        return None
    return next_date
