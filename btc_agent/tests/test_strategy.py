"""Tests for strategy.py's crossover and swing-reversal math - small
windows, hand-computable."""

import pandas as pd
import pytest

from btc_agent.strategy import Action, MomentumStrategy, SwingReversalStrategy


def make_ohlcv(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1_000] * len(closes)},
        index=dates,
    )


def make_intraday_ohlcv(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="h")
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


class TestSwingReversalConstruction:
    def test_rejects_too_small_lookback(self):
        with pytest.raises(ValueError):
            SwingReversalStrategy(lookback_bars=1)

    def test_rejects_non_positive_reversal_pct(self):
        with pytest.raises(ValueError):
            SwingReversalStrategy(reversal_pct=0)


class TestSwingReversalMath:
    def test_not_enough_bars_holds(self):
        strategy = SwingReversalStrategy(lookback_bars=3, reversal_pct=0.05)
        data = make_intraday_ohlcv([100.0, 100.0, 100.0])  # needs 4 bars (lookback + 1)
        signal = strategy.generate_signal(data)
        assert signal.action == Action.HOLD
        assert "warming up" in signal.reason

    def test_pullback_past_threshold_produces_buy(self):
        # trailing 3-bar window (excludes current bar) = [100, 100, 100] -> high=100
        # current close = 90 -> 10% drop from high, past the 5% threshold
        strategy = SwingReversalStrategy(lookback_bars=3, reversal_pct=0.05)
        data = make_intraday_ohlcv([100.0, 100.0, 100.0, 90.0])
        signal = strategy.generate_signal(data)
        assert signal.action == Action.BUY
        assert "below" in signal.reason

    def test_bounce_past_threshold_produces_sell(self):
        # trailing window low=100, current close=110 -> 10% bounce, past 5%
        strategy = SwingReversalStrategy(lookback_bars=3, reversal_pct=0.05)
        data = make_intraday_ohlcv([100.0, 100.0, 100.0, 110.0])
        signal = strategy.generate_signal(data)
        assert signal.action == Action.SELL
        assert "above" in signal.reason

    def test_move_under_threshold_holds(self):
        # only a 2% drop, below the 5% threshold
        strategy = SwingReversalStrategy(lookback_bars=3, reversal_pct=0.05)
        data = make_intraday_ohlcv([100.0, 100.0, 100.0, 98.0])
        signal = strategy.generate_signal(data)
        assert signal.action == Action.HOLD
        assert signal.reason == "no reversal threshold crossed"

    def test_can_fire_multiple_times_across_a_single_day(self):
        # 12 hourly bars: drift down (buy trigger), then sharply up (sell
        # trigger) - demonstrates the whole point of running this on
        # intraday bars instead of daily ones.
        strategy = SwingReversalStrategy(lookback_bars=3, reversal_pct=0.05)
        closes = [100.0, 100.0, 100.0, 89.0, 89.0, 89.0, 89.0, 105.0]
        data = make_intraday_ohlcv(closes)

        buy_signal = strategy.generate_signal(data.iloc[:4])   # drop to 89
        sell_signal = strategy.generate_signal(data.iloc[:8])  # bounce to 105

        assert buy_signal.action == Action.BUY
        assert sell_signal.action == Action.SELL
        assert data.index[3].date() == data.index[7].date()  # same calendar day
