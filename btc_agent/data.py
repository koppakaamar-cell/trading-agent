"""
Historical BTC-USD bars for backtesting.

Single-symbol, so this is deliberately thinner than the equity scaffold's
data_provider.py - no CSV loader, no multi-symbol plumbing, just "get me
BTC history as OHLCV."
"""

import pandas as pd

REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def load_btc_history(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    Requires the `yfinance` package. Daily bars only - yfinance's free
    intraday crypto history is short-range (days, not years), so anything
    wanting to backtest an intraday BTC strategy needs a different data
    source; this covers swing/position-scale strategies on daily closes.

    Crypto trades 24/7 with no exchange holidays, so unlike equities this
    should return one row per calendar day with no gaps (beyond whatever
    yfinance itself is missing).
    """
    import yfinance as yf

    raw = yf.download(symbol, start=start, end=end, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]
    raw.index.name = "date"
    return raw[REQUIRED_COLUMNS]


# yfinance's actual lookback limit per intraday interval - a request beyond
# this comes back empty rather than erroring, so it's worth clamping to
# instead of silently returning nothing.
_MAX_INTRADAY_DAYS = {"1m": 7, "2m": 60, "5m": 60, "15m": 60, "30m": 60, "60m": 729, "1h": 729}


def load_btc_intraday_history(symbol: str, days: int, interval: str = "1h") -> pd.DataFrame:
    """
    Intraday BTC-USD bars, for strategies that need to react within a day
    (e.g. multiple trades per day) rather than once per daily close.

    yfinance's free intraday history is short-range compared to daily bars
    - "1h" covers ~730 days back, "1m" only ~7 - so `days` is silently
    clamped to whatever the requested `interval` actually supports.
    """
    import yfinance as yf

    limit = _MAX_INTRADAY_DAYS.get(interval)
    if limit is not None and days > limit:
        days = limit

    end = pd.Timestamp.utcnow().normalize()
    start = end - pd.Timedelta(days=days)
    raw = yf.download(symbol, start=start, end=end, interval=interval, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]
    raw.index.name = "date"
    return raw[REQUIRED_COLUMNS]
