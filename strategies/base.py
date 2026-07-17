"""
Base strategy interface.

Every strategy is a pure function of historical price data -> a Signal.
Strategies do NOT place orders, size positions, or know about risk limits.
That separation is deliberate: it lets you backtest a strategy's raw edge
independently of risk management, and swap strategies without touching
execution or risk code.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Action(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    symbol: str
    action: Action
    strength: float  # 0.0-1.0, how confident/strong the signal is
    reason: str       # human-readable explanation, useful for logs and for
                       # Claude to relay to you before placing a trade


class Strategy(ABC):
    """
    Subclass this and implement `generate_signal`.

    `data` is a DataFrame of historical OHLCV bars for a single symbol,
    indexed by date, oldest first, with columns:
    ['open', 'high', 'low', 'close', 'volume'].

    Only use data up to and including the last row - never look ahead.
    The backtester will call this once per bar with the data truncated
    to that point in time, so lookahead bias is structurally prevented
    as long as you don't reach outside `data`.
    """

    name: str = "base_strategy"

    @abstractmethod
    def generate_signal(self, symbol: str, data: pd.DataFrame) -> Signal:
        raise NotImplementedError

    def min_bars_required(self) -> int:
        """Override if your strategy needs a warm-up period (e.g. a 50-day MA
        needs 50 bars before it can produce a real signal)."""
        return 1
