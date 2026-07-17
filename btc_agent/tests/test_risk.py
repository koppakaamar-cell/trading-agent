"""Tests for risk.py - no network, pure logic against constructed states."""

import pytest

from btc_agent.risk import PortfolioState, RiskLimits, RiskManager, TradeRejected
from btc_agent.strategy import Action, Signal


def make_state(**overrides) -> PortfolioState:
    defaults = dict(equity=2_000.0, cash=2_000.0)
    defaults.update(overrides)
    return PortfolioState(**defaults)


class TestDailyLossBreached:
    def test_no_loss_does_not_breach(self):
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.05))
        state = make_state(equity=2_000.0, equity_at_day_start=2_000.0)
        assert rm.daily_loss_breached(state) is False

    def test_unrealized_loss_breaches(self):
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.05))
        state = make_state(equity=1_880.0, equity_at_day_start=2_000.0)  # -6%
        assert rm.daily_loss_breached(state) is True

    def test_zero_or_negative_equity_breaches(self):
        rm = RiskManager()
        state = make_state(equity=0.0, equity_at_day_start=2_000.0)
        assert rm.daily_loss_breached(state) is True


class TestCheckTrailingStop:
    def test_no_position_never_triggers(self):
        rm = RiskManager(RiskLimits(trailing_stop_pct=0.10))
        state = make_state(position=None)
        assert rm.check_trailing_stop(state, 50_000.0) is False

    def test_triggers_from_entry_with_no_prior_high(self):
        rm = RiskManager(RiskLimits(trailing_stop_pct=0.10))
        state = make_state(position={"qty": 0.02, "avg_price": 60_000.0})
        assert rm.check_trailing_stop(state, 53_000.0) is True  # -11.7%

    def test_rally_updates_peak_without_forcing_exit(self):
        rm = RiskManager(RiskLimits(trailing_stop_pct=0.10))
        state = make_state(position={"qty": 0.02, "avg_price": 60_000.0})
        assert rm.check_trailing_stop(state, 90_000.0) is False
        assert state.position["peak_price"] == 90_000.0

    def test_fires_on_pullback_from_peak_not_entry(self):
        rm = RiskManager(RiskLimits(trailing_stop_pct=0.10))
        state = make_state(position={"qty": 0.02, "avg_price": 60_000.0})
        assert rm.check_trailing_stop(state, 90_000.0) is False  # sets peak to 90k
        assert rm.check_trailing_stop(state, 79_000.0) is True   # -12.2% from the 90k peak


class TestSizeAndValidate:
    def make_signal(self, action=Action.BUY):
        return Signal(action=action, strength=1.0, reason="test")

    def test_hold_signal_sizes_to_zero(self):
        rm = RiskManager()
        state = make_state()
        assert rm.size_and_validate(self.make_signal(Action.HOLD), state, 50_000.0) == 0.0

    def test_normal_buy_sizes_fractionally_using_full_cash(self):
        rm = RiskManager(RiskLimits(max_position_pct=1.0))
        state = make_state(equity=2_000.0, cash=2_000.0)
        qty = rm.size_and_validate(self.make_signal(), state, 50_000.0)
        assert qty == pytest.approx(0.04)  # $2000 / $50,000

    def test_max_position_pct_below_1_caps_below_full_cash(self):
        rm = RiskManager(RiskLimits(max_position_pct=0.5))
        state = make_state(equity=2_000.0, cash=2_000.0)
        qty = rm.size_and_validate(self.make_signal(), state, 50_000.0)
        assert qty == pytest.approx(0.02)  # $1000 / $50,000

    def test_rejects_when_daily_loss_breached(self):
        rm = RiskManager(RiskLimits(max_daily_loss_pct=0.05))
        state = make_state(equity=1_800.0, equity_at_day_start=2_000.0, cash=1_800.0)
        with pytest.raises(TradeRejected, match="daily loss"):
            rm.size_and_validate(self.make_signal(), state, 50_000.0)

    def test_rejects_when_already_holding_position(self):
        rm = RiskManager()
        state = make_state(position={"qty": 0.01, "avg_price": 50_000.0})
        with pytest.raises(TradeRejected, match="already holding"):
            rm.size_and_validate(self.make_signal(), state, 50_000.0)

    def test_rejects_invalid_price(self):
        rm = RiskManager()
        state = make_state()
        with pytest.raises(TradeRejected, match="invalid price"):
            rm.size_and_validate(self.make_signal(), state, 0.0)

    def test_sizing_is_capped_by_available_cash(self):
        rm = RiskManager(RiskLimits(max_position_pct=1.0))
        state = make_state(equity=2_000.0, cash=100.0)  # mostly already deployed
        qty = rm.size_and_validate(self.make_signal(), state, 50_000.0)
        assert qty == pytest.approx(0.002)  # capped by cash, not equity
