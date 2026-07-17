"""
BTC momentum strategy: dual moving-average crossover.

Pure signal generation - no orders, no position sizing, no risk checks.
Same well-understood technique as the equity scaffold's momentum strategy,
but this is its own implementation: single-symbol, and free to diverge
(e.g. different windows, different signal logic) without touching
anything equity-side.
"""

from dataclasses import dataclass
from enum import Enum

import pandas as pd


class Action(Enum):
    BUY = "buy"
    SELL = "sell"
    HOLD = "hold"


@dataclass
class Signal:
    action: Action
    strength: float  # 0.0-1.0
    reason: str


class MomentumStrategy:
    name = "btc_momentum_ma_crossover"

    def __init__(self, fast_window: int = 20, slow_window: int = 50):
        if fast_window >= slow_window:
            raise ValueError("fast_window must be < slow_window")
        self.fast_window = fast_window
        self.slow_window = slow_window

    def min_bars_required(self) -> int:
        return self.slow_window + 1

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """`data` is OHLCV bars up to and including "now" - never look
        further ahead than the last row, or backtests lie."""
        if len(data) < self.min_bars_required():
            return Signal(Action.HOLD, 0.0, "warming up: not enough bars yet")

        close = data["close"]
        fast_ma = close.rolling(self.fast_window).mean()
        slow_ma = close.rolling(self.slow_window).mean()

        fast_now, fast_prev = fast_ma.iloc[-1], fast_ma.iloc[-2]
        slow_now, slow_prev = slow_ma.iloc[-1], slow_ma.iloc[-2]

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        spread_pct = abs(fast_now - slow_now) / slow_now
        strength = min(spread_pct * 10, 1.0)

        if crossed_up:
            return Signal(Action.BUY, max(strength, 0.5),
                           f"{self.fast_window}MA crossed above {self.slow_window}MA")
        if crossed_down:
            return Signal(Action.SELL, max(strength, 0.5),
                           f"{self.fast_window}MA crossed below {self.slow_window}MA")
        return Signal(Action.HOLD, 0.0, "no crossover")
