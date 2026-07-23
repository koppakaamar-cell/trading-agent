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
