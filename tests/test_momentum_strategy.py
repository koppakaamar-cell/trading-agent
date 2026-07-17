"""
Tests for strategies/momentum.py - the actual trading logic (dual moving-
average crossover). Pure logic against constructed price series; no
network calls. Uses small windows (fast=2, slow=3) so crossover scenarios
can be hand-computed and verified exactly, rather than relying on real
market data where the "right" answer isn't independently known.
"""

import pandas as pd
import pytest

from strategies.base import Action
from strategies.momentum import MomentumStrategy


def make_df(closes: list[float], start: str = "2024-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1_000_000] * len(closes)},
        index=dates,
    )


class TestConstruction:
    def test_valid_windows_construct(self):
        strategy = MomentumStrategy(fast_window=20, slow_window=50)
        assert strategy.fast_window == 20
        assert strategy.slow_window == 50
        assert strategy.name == "momentum_ma_crossover"

    def test_defaults(self):
        strategy = MomentumStrategy()
        assert strategy.fast_window == 20
        assert strategy.slow_window == 50

    def test_fast_equal_to_slow_rejected(self):
        with pytest.raises(ValueError, match="fast_window must be < slow_window"):
            MomentumStrategy(fast_window=50, slow_window=50)

    def test_fast_greater_than_slow_rejected(self):
        with pytest.raises(ValueError, match="fast_window must be < slow_window"):
            MomentumStrategy(fast_window=60, slow_window=50)


class TestMinBarsRequired:
    def test_matches_slow_window_plus_one(self):
        strategy = MomentumStrategy(fast_window=20, slow_window=50)
        assert strategy.min_bars_required() == 51

    def test_small_windows(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        assert strategy.min_bars_required() == 4


class TestWarmup:
    def test_too_few_bars_holds_with_warming_up_reason(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_df([100.0, 100.0, 100.0])  # 3 bars, needs 4

        signal = strategy.generate_signal("TEST", data)

        assert signal.action == Action.HOLD
        assert signal.strength == 0.0
        assert "warming up" in signal.reason

    def test_zero_bars_holds(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_df([])

        signal = strategy.generate_signal("TEST", data)

        assert signal.action == Action.HOLD
        assert "warming up" in signal.reason


class TestCrossoverDetection:
    """fast=2, slow=3 with exactly min_bars_required (4) bars, so both MAs
    are valid (non-NaN) at the last two positions - the minimum case where
    a real signal can fire. Hand-computed:
      fast_ma[i] = avg(close[i-1], close[i])
      slow_ma[i] = avg(close[i-2], close[i-1], close[i])
    """

    def test_fast_crossing_above_slow_signals_buy(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        # closes: 100, 100, 100, 110
        # fast_ma: [-, 100, 100, 105]   slow_ma: [-, -, 100, 103.33]
        # prev: fast=100 <= slow=100 (True); now: fast=105 > slow=103.33 (True) -> crossed up
        data = make_df([100.0, 100.0, 100.0, 110.0])

        signal = strategy.generate_signal("TEST", data)

        assert signal.action == Action.BUY
        assert signal.reason == "2MA crossed above 3MA"
        assert signal.strength >= 0.5  # floor for any confirmed crossing

    def test_fast_crossing_below_slow_signals_sell(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        # closes: 100, 100, 100, 90
        # fast_ma: [-, 100, 100, 95]   slow_ma: [-, -, 100, 96.67]
        # prev: fast=100 >= slow=100 (True); now: fast=95 < slow=96.67 (True) -> crossed down
        data = make_df([100.0, 100.0, 100.0, 90.0])

        signal = strategy.generate_signal("TEST", data)

        assert signal.action == Action.SELL
        assert signal.reason == "2MA crossed below 3MA"
        assert signal.strength >= 0.5

    def test_flat_prices_hold_with_no_crossover(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_df([100.0, 100.0, 100.0, 100.0])

        signal = strategy.generate_signal("TEST", data)

        assert signal.action == Action.HOLD
        assert signal.strength == 0.0
        assert signal.reason == "no crossover"

    def test_fast_already_above_slow_no_new_cross_holds(self):
        """Fast already above slow on both the previous and current bar -
        no fresh crossover, so this must not fire another BUY."""
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        # closes: 100, 110, 120, 130 - fast stays above slow the whole time once warmed up
        data = make_df([100.0, 110.0, 120.0, 130.0])

        signal = strategy.generate_signal("TEST", data)

        assert signal.action == Action.HOLD
        assert signal.reason == "no crossover"


class TestStrength:
    def test_small_spread_crossing_floors_at_half(self):
        """Even a razor-thin crossover should report at least 0.5
        strength, not something near-zero that undersells the signal."""
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_df([100.0, 100.0, 100.0, 110.0])  # spread_pct ~1.6% -> raw strength ~0.16

        signal = strategy.generate_signal("TEST", data)

        assert signal.strength == pytest.approx(0.5)

    def test_large_spread_crossing_caps_at_one(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_df([100.0, 100.0, 100.0, 200.0])  # spread_pct ~12.5% -> raw strength 1.25, capped

        signal = strategy.generate_signal("TEST", data)

        assert signal.action == Action.BUY
        assert signal.strength == pytest.approx(1.0)

    def test_no_crossover_always_zero_strength(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_df([100.0, 100.0, 100.0, 100.0])

        signal = strategy.generate_signal("TEST", data)

        assert signal.strength == 0.0


class TestExtraHistoryDoesNotBreakDetection:
    def test_crossover_still_detected_with_longer_history(self):
        """Older bars beyond what the rolling windows need shouldn't
        change the outcome - only the trailing window matters."""
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        # 5 bars of flat history before the same crossover as the BUY test
        data = make_df([100.0, 100.0, 100.0, 100.0, 100.0, 100.0, 110.0])

        signal = strategy.generate_signal("TEST", data)

        assert signal.action == Action.BUY
        assert signal.reason == "2MA crossed above 3MA"


class TestSymbolPassthrough:
    def test_signal_carries_requested_symbol(self):
        strategy = MomentumStrategy(fast_window=2, slow_window=3)
        data = make_df([100.0, 100.0, 100.0, 110.0])

        signal = strategy.generate_signal("MSFT", data)

        assert signal.symbol == "MSFT"
