"""Tests for strategy.py's crossover math - small windows, hand-computable."""

import pandas as pd
import pytest

from btc_agent.strategy import Action, MomentumStrategy


def make_ohlcv(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1_000] * len(closes)},
        index=dates,
    )


class TestConstruction:
    def test_rejects_fast_not_less_than_slow(self):
        with pytest.raises(ValueError):
            MomentumStrategy(fast_window=5, slow_window=5)


class TestCrossoverMath:
    def test_not_enough_bars_holds(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_ohlcv([100.0, 100.0])  # needs 4 bars (slow_window + 1)
        signal = strategy.generate_signal(data)
        assert signal.action == Action.HOLD
        assert "warming up" in signal.reason

    def test_crossed_up_produces_buy(self):
        # fast(2)/slow(3) MAs computed by hand:
        # closes: 100, 100, 100, 130
        # slow_ma[-2] = mean(100,100,100)=100, slow_ma[-1] = mean(100,100,130)=110
        # fast_ma[-2] = mean(100,100)=100, fast_ma[-1] = mean(100,130)=115
        # prev: fast(100) <= slow(100) True; now: fast(115) > slow(110) True -> crossed up
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_ohlcv([100.0, 100.0, 100.0, 130.0])
        signal = strategy.generate_signal(data)
        assert signal.action == Action.BUY
        assert "crossed above" in signal.reason

    def test_crossed_down_produces_sell(self):
        # closes: 100, 130, 130, 70
        # slow_ma[-2] = mean(100,130,130)=120, slow_ma[-1] = mean(130,130,70)=110
        # fast_ma[-2] = mean(130,130)=130, fast_ma[-1] = mean(130,70)=100
        # prev: fast(130) >= slow(120) True; now: fast(100) < slow(110) True -> crossed down
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_ohlcv([100.0, 130.0, 130.0, 70.0])
        signal = strategy.generate_signal(data)
        assert signal.action == Action.SELL
        assert "crossed below" in signal.reason

    def test_no_crossover_holds(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_ohlcv([100.0, 100.0, 100.0, 100.0])
        signal = strategy.generate_signal(data)
        assert signal.action == Action.HOLD
        assert signal.reason == "no crossover"
