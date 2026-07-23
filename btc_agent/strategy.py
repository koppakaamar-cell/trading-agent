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


class SwingReversalStrategy:
    """Buy on a % pullback from the recent local high, sell on a % bounce
    off the recent local low. Meant to run on intraday bars (see data.py's
    load_btc_intraday_history) so the "recent" window is hours, not days -
    this is what makes multiple round-trips in a single day possible.

    This is deliberately NOT "buy at the day's low, sell at the day's
    high": that target can only be known in hindsight, after the day is
    over, so a backtest (or a live strategy) that tried to hit it exactly
    would be cheating on future information. Reacting to a threshold move
    away from the recent high/low, using only bars already seen, is the
    closest tradeable approximation of that idea.
    """

    name = "btc_swing_reversal"

    def __init__(self, lookback_bars: int = 12, reversal_pct: float = 0.015):
        if lookback_bars < 2:
            raise ValueError("lookback_bars must be >= 2")
        if reversal_pct <= 0:
            raise ValueError("reversal_pct must be > 0")
        self.lookback_bars = lookback_bars
        self.reversal_pct = reversal_pct

    def min_bars_required(self) -> int:
        return self.lookback_bars + 1

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        """`data` is OHLCV bars up to and including "now". The lookback
        window excludes the current bar, so the high/low it compares
        against is always known strictly before the signal fires."""
        if len(data) < self.min_bars_required():
            return Signal(Action.HOLD, 0.0, "warming up: not enough bars yet")

        window = data.iloc[-(self.lookback_bars + 1):-1]
        recent_high = window["high"].max()
        recent_low = window["low"].min()
        price = data["close"].iloc[-1]

        drop_from_high = (recent_high - price) / recent_high
        rise_from_low = (price - recent_low) / recent_low

        buy_trigger = drop_from_high >= self.reversal_pct
        sell_trigger = rise_from_low >= self.reversal_pct

        if buy_trigger and (not sell_trigger or drop_from_high >= rise_from_low):
            strength = max(min(drop_from_high * 10, 1.0), 0.5)
            return Signal(Action.BUY, strength,
                           f"price {drop_from_high:.1%} below {self.lookback_bars}-bar high")
        if sell_trigger:
            strength = max(min(rise_from_low * 10, 1.0), 0.5)
            return Signal(Action.SELL, strength,
                           f"price {rise_from_low:.1%} above {self.lookback_bars}-bar low")
        return Signal(Action.HOLD, 0.0, "no reversal threshold crossed")
