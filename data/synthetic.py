"""
Synthetic OHLCV data generator, purely for smoke-testing the backtest
engine and strategy logic without needing a live market data connection.
Do NOT use this to evaluate whether a strategy is actually good - it's a
random walk, not a market. Use load_from_yfinance or real historical data
for real backtests.
"""

import numpy as np
import pandas as pd


def generate_synthetic_ohlcv(
    symbol: str,
    days: int = 300,
    start_price: float = 100.0,
    drift: float = 0.0003,
    volatility: float = 0.015,
    seed: int | None = None,
) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=days)

    returns = rng.normal(drift, volatility, size=days)
    close = start_price * np.exp(np.cumsum(returns))

    high = close * (1 + rng.uniform(0, 0.01, size=days))
    low = close * (1 - rng.uniform(0, 0.01, size=days))
    open_ = close * (1 + rng.normal(0, 0.005, size=days))
    volume = rng.integers(1_000_000, 5_000_000, size=days)

    df = pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=dates,
    )
    df.index.name = "date"
    return df
