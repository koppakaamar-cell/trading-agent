"""
Data provider abstraction.

Strategies and the backtester only care about a DataFrame with
['open','high','low','close','volume'] columns, indexed by date. This
module is where you plug in an actual data source.

- For BACKTESTING: use `load_from_csv` or `load_from_yfinance` to get
  historical bars.
- For LIVE / PAPER trading in Claude Code: Claude itself calls the
  Robinhood MCP tool `get_equity_quotes` (or similar) directly, then hands
  the resulting prices to your strategy code. This file includes a small
  helper, `bars_from_quote_history`, to normalize whatever shape Robinhood's
  MCP returns into the same DataFrame format used everywhere else, so your
  strategy code never has to know or care whether it's running on
  backtest data or live MCP data.
"""

import pandas as pd


REQUIRED_COLUMNS = ["open", "high", "low", "close", "volume"]


def load_from_csv(path: str, date_col: str = "date") -> pd.DataFrame:
    df = pd.read_csv(path, parse_dates=[date_col])
    df = df.set_index(date_col).sort_index()
    missing = set(REQUIRED_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"CSV at {path} is missing required columns: {missing}")
    return df[REQUIRED_COLUMNS]


def load_from_yfinance(symbol: str, start: str, end: str) -> pd.DataFrame:
    """
    Requires the `yfinance` package (pip install yfinance --break-system-packages).
    Kept as a separate function so backtests don't require network access
    unless you explicitly call this.
    """
    import yfinance as yf

    raw = yf.download(symbol, start=start, end=end, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = [c[0].lower() for c in raw.columns]
    else:
        raw.columns = [c.lower() for c in raw.columns]
    raw.index.name = "date"
    return raw[REQUIRED_COLUMNS]


def bars_from_quote_history(raw_quotes: list[dict]) -> pd.DataFrame:
    """
    Normalizes a list of quote dicts (as might come back from the Robinhood
    MCP server's historical quote tools) into the standard OHLCV DataFrame.

    Expects each dict to have at least: date/time, open, high, low, close,
    volume keys - adjust the key names below once you see the actual shape
    the MCP tool returns, since that isn't fully documented yet.
    """
    df = pd.DataFrame(raw_quotes)
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df[REQUIRED_COLUMNS]
