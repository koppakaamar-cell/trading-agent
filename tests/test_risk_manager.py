"""
Tests for risk/risk_manager.py - the layer that's supposed to keep you
solvent, so it's the code most worth trusting. No network calls; every
test here is pure logic against constructed PortfolioState objects.
"""

import pytest

from risk.risk_manager import PortfolioState, RiskLimits, RiskManager, TradeRejected
from strategies.base import Action, Signal


def make_state(**overrides) -> PortfolioState:
    defaults = dict(equity=10_000.0, cash=10_000.0)
    defaults.update(overrides)
    return PortfolioState(**defaults)


class TestDailyLossBreached:
    def test_no_loss_does_not_breach(self):
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.03))
        state = make_state(equity=10_000.0, equity_at_day_start=10_000.0)
        assert rm.daily_loss_breached(state) is False

    def test_realized_loss_alone_breaches(self):
        """The original behavior this code path was built for: booked
        losses past the limit halt new trades."""
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.03))
        state = make_state(equity=9_600.0, equity_at_day_start=10_000.0, realized_pnl_today=-400.0)
        assert rm.daily_loss_breached(state) is True

    def test_unrealized_loss_alone_breaches(self):
        """Regression test: a position deep in unrealized loss with
        nothing sold yet (realized_pnl_today == 0) must still halt new
        buys. Before the mark-to-market fix, this returned False because
        daily_loss_breached only looked at realized_pnl_today, letting the
        risk manager keep approving buys straight into a crash."""
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.03))
        state = make_state(equity=9_000.0, equity_at_day_start=10_000.0)
        assert state.realized_pnl_today == 0.0
        assert rm.daily_loss_breached(state) is True

    def test_loss_just_under_threshold_does_not_breach(self):
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.03))
        state = make_state(equity=9_701.0, equity_at_day_start=10_000.0)  # 2.99% loss
        assert rm.daily_loss_breached(state) is False

    def test_loss_exactly_at_threshold_breaches(self):
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.03))
        state = make_state(equity=9_700.0, equity_at_day_start=10_000.0)  # exactly 3%
        assert rm.daily_loss_breached(state) is True

    def test_zero_or_negative_equity_breaches(self):
        rm = RiskManager()
        state = make_state(equity=0.0, equity_at_day_start=10_000.0)
        assert rm.daily_loss_breached(state) is True
        state2 = make_state(equity=-500.0, equity_at_day_start=10_000.0)
        assert rm.daily_loss_breached(state2) is True

    def test_equity_at_day_start_defaults_to_construction_equity(self):
        """PortfolioState.__post_init__ should seed equity_at_day_start
        from equity when not explicitly set, so a freshly-constructed
        state never breaches on day one."""
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.03))
        state = PortfolioState(equity=10_000.0, cash=10_000.0)
        assert state.equity_at_day_start == 10_000.0
        assert rm.daily_loss_breached(state) is False


class TestCheckStopLosses:
    def test_stop_loss_triggers_from_entry(self):
        """With no prior high, the peak is the entry price - so an initial
        drop past trailing_stop_pct closes the position exactly like a
        fixed stop-loss would."""
        rm = RiskManager(RiskLimits(trailing_stop_pct=0.05))
        state = make_state(positions={"AAPL": {"qty": 10, "avg_price": 100.0}})
        to_close = rm.check_stop_losses(state, {"AAPL": 94.0})  # -6%
        assert to_close == ["AAPL"]

    def test_rally_does_not_force_exit_and_updates_peak(self):
        """No fixed take-profit target: a position that keeps making new
        highs stays open, and its peak is tracked for the trailing stop."""
        rm = RiskManager(RiskLimits(trailing_stop_pct=0.20))
        state = make_state(positions={"AAPL": {"qty": 10, "avg_price": 100.0}})
        to_close = rm.check_stop_losses(state, {"AAPL": 150.0})  # +50%, no target to hit
        assert to_close == []
        assert state.positions["AAPL"]["peak_price"] == 150.0

    def test_trailing_stop_fires_on_pullback_from_peak(self):
        rm = RiskManager(RiskLimits(trailing_stop_pct=0.20))
        state = make_state(positions={"AAPL": {"qty": 10, "avg_price": 100.0}})
        assert rm.check_stop_losses(state, {"AAPL": 150.0}) == []  # sets peak to 150
        to_close = rm.check_stop_losses(state, {"AAPL": 115.0})  # -23% from the 150 peak
        assert to_close == ["AAPL"]

    def test_within_band_does_not_trigger(self):
        rm = RiskManager(RiskLimits(trailing_stop_pct=0.05))
        state = make_state(positions={"AAPL": {"qty": 10, "avg_price": 100.0}})
        to_close = rm.check_stop_losses(state, {"AAPL": 103.0})
        assert to_close == []

    def test_missing_price_is_skipped_not_errored(self):
        rm = RiskManager()
        state = make_state(positions={"AAPL": {"qty": 10, "avg_price": 100.0}})
        to_close = rm.check_stop_losses(state, {})
        assert to_close == []


class TestSizeAndValidate:
    def make_signal(self, action=Action.BUY, symbol="AAPL"):
        return Signal(symbol=symbol, action=action, strength=1.0, reason="test")

    def test_hold_signal_sizes_to_zero(self):
        rm = RiskManager()
        state = make_state()
        assert rm.size_and_validate(self.make_signal(Action.HOLD), state, 100.0) == 0

    def test_normal_buy_sizes_within_limits(self):
        rm = RiskManager(RiskLimits(max_position_pct=0.10, max_single_trade_pct=0.05))
        state = make_state(equity=10_000.0, cash=10_000.0)
        qty = rm.size_and_validate(self.make_signal(), state, 100.0)
        # capped by max_single_trade_pct (5% of 10k = $500) -> 5 shares
        assert qty == 5

    def test_rejects_when_daily_loss_breached(self):
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.03))
        state = make_state(equity=9_000.0, equity_at_day_start=10_000.0, cash=9_000.0)
        with pytest.raises(TradeRejected, match="daily loss"):
            rm.size_and_validate(self.make_signal(), state, 100.0)

    def test_rejects_when_max_open_positions_reached(self):
        rm = RiskManager(RiskLimits(max_open_positions=2))
        state = make_state(positions={
            "AAPL": {"qty": 1, "avg_price": 100.0},
            "MSFT": {"qty": 1, "avg_price": 100.0},
        })
        with pytest.raises(TradeRejected, match="max open positions"):
            rm.size_and_validate(self.make_signal(symbol="SPY"), state, 100.0)

    def test_rejects_when_already_holding_symbol(self):
        rm = RiskManager()
        state = make_state(positions={"AAPL": {"qty": 1, "avg_price": 100.0}})
        with pytest.raises(TradeRejected, match="already holding"):
            rm.size_and_validate(self.make_signal(symbol="AAPL"), state, 100.0)

    def test_rejects_invalid_price(self):
        rm = RiskManager()
        state = make_state()
        with pytest.raises(TradeRejected, match="invalid price"):
            rm.size_and_validate(self.make_signal(), state, 0.0)

    def test_rejects_when_size_rounds_to_zero(self):
        rm = RiskManager(RiskLimits(max_position_pct=0.10, max_single_trade_pct=0.05))
        state = make_state(equity=10_000.0, cash=10_000.0)
        # $500 max trade, but price of $10,000/share -> 0 shares
        with pytest.raises(TradeRejected, match="rounds to 0"):
            rm.size_and_validate(self.make_signal(), state, 10_000.0)

    def test_sizing_is_capped_by_available_cash(self):
        rm = RiskManager(RiskLimits(max_position_pct=0.50, max_single_trade_pct=0.50))
        state = make_state(equity=10_000.0, cash=200.0)  # mostly invested already
        qty = rm.size_and_validate(self.make_signal(), state, 100.0)
        assert qty == 2  # capped by cash, not the 50% equity limits
