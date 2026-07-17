"""
Simple momentum / trend-following strategy.

Logic:
  - Fast moving average crosses above slow moving average -> BUY signal
  - Fast moving average crosses below slow moving average -> SELL signal
  - Otherwise -> HOLD

This is a deliberately simple, well-understood starting point (a classic
dual moving-average crossover). It is NOT tuned or validated for any
particular symbol or timeframe - treat it as a scaffold to backtest,
inspect, and improve, not as a ready-to-fund strategy.
"""

import pandas as pd

from strategies.base import Action, Signal, Strategy


class MomentumStrategy(Strategy):
    name = "momentum_ma_crossover"

    def __init__(self, fast_window: int = 20, slow_window: int = 50):
        if fast_window >= slow_window:
            raise ValueError("fast_window must be < slow_window")
        self.fast_window = fast_window
        self.slow_window = slow_window

    def min_bars_required(self) -> int:
        return self.slow_window + 1

    def generate_signal(self, symbol: str, data: pd.DataFrame) -> Signal:
        if len(data) < self.min_bars_required():
            return Signal(symbol, Action.HOLD, 0.0, "warming up: not enough bars yet")

        close = data["close"]
        fast_ma = close.rolling(self.fast_window).mean()
        slow_ma = close.rolling(self.slow_window).mean()

        fast_now, fast_prev = fast_ma.iloc[-1], fast_ma.iloc[-2]
        slow_now, slow_prev = slow_ma.iloc[-1], slow_ma.iloc[-2]

        crossed_up = fast_prev <= slow_prev and fast_now > slow_now
        crossed_down = fast_prev >= slow_prev and fast_now < slow_now

        # Strength scales with how far apart the MAs are, as a rough proxy
        # for trend conviction. Capped at 1.0.
        spread_pct = abs(fast_now - slow_now) / slow_now
        strength = min(spread_pct * 10, 1.0)

        if crossed_up:
            return Signal(
                symbol, Action.BUY, max(strength, 0.5),
                f"{self.fast_window}MA crossed above {self.slow_window}MA",
            )
        if crossed_down:
            return Signal(
                symbol, Action.SELL, max(strength, 0.5),
                f"{self.fast_window}MA crossed below {self.slow_window}MA",
            )
        return Signal(symbol, Action.HOLD, 0.0, "no crossover")
