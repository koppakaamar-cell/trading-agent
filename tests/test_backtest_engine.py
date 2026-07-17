"""
Integration tests for backtest/engine.py - runs the real engine against
small, constructed (not network-fetched) price series with a scripted
strategy, so behavior is fully deterministic.
"""

import pandas as pd
import pytest

from backtest.engine import run_backtest
from risk.risk_manager import RiskLimits, RiskManager
from strategies.base import Action, Signal, Strategy


def make_ohlcv(closes: list[float], start: str = "2024-01-02") -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=len(closes))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1_000_000] * len(closes)},
        index=dates,
    )


class ScriptedStrategy(Strategy):
    """Returns a specific Action for (symbol, date) pairs from a fixed
    script, HOLD otherwise - lets a test dictate exactly when a signal
    fires instead of depending on real crossover math."""

    name = "scripted_test_strategy"

    def __init__(self, script: dict):
        self.script = script  # {(symbol, "YYYY-MM-DD"): Action}

    def min_bars_required(self) -> int:
        return 1

    def generate_signal(self, symbol: str, data: pd.DataFrame) -> Signal:
        date_str = data.index[-1].strftime("%Y-%m-%d")
        action = self.script.get((symbol, date_str), Action.HOLD)
        return Signal(symbol=symbol, action=action, strength=1.0, reason="scripted")


class TestBasicFlow:
    def test_buy_and_hold_produces_expected_equity(self):
        dates = pd.bdate_range(start="2024-01-02", periods=3)
        strategy = ScriptedStrategy({("A", dates[0].strftime("%Y-%m-%d")): Action.BUY})
        price_data = {"A": make_ohlcv([100.0, 100.0, 100.0])}
        risk_manager = RiskManager(RiskLimits(max_position_pct=1.0, max_single_trade_pct=1.0))

        result = run_backtest(strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager)

        assert len(result.trades) == 1
        assert result.trades[0].action == "buy"
        assert result.trades[0].qty == 10  # $1000 / $100
        assert result.ending_equity == pytest.approx(1_000.0)
        assert len(result.equity_curve) == 3

    def test_stop_loss_forces_exit_regardless_of_strategy_signal(self):
        dates = pd.bdate_range(start="2024-01-02", periods=2)
        strategy = ScriptedStrategy({("A", dates[0].strftime("%Y-%m-%d")): Action.BUY})
        price_data = {"A": make_ohlcv([100.0, 90.0])}  # -10%, past the 5% trailing stop
        risk_manager = RiskManager(RiskLimits(max_position_pct=1.0, max_single_trade_pct=1.0, trailing_stop_pct=0.05))

        result = run_backtest(strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager)

        assert [t.action for t in result.trades] == ["buy", "sell"]
        assert result.trades[1].reason == "stop-loss/take-profit"
        assert result.trades[1].price == pytest.approx(90.0)


class TestCostsModeling:
    def test_slippage_and_commission_applied_to_buy_fill(self):
        dates = pd.bdate_range(start="2024-01-02", periods=1)
        strategy = ScriptedStrategy({("A", dates[0].strftime("%Y-%m-%d")): Action.BUY})
        price_data = {"A": make_ohlcv([100.0])}
        risk_manager = RiskManager(RiskLimits(max_position_pct=0.5, max_single_trade_pct=0.5))

        result = run_backtest(
            strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager,
            slippage_bps=100, commission_per_trade=2.0,  # 1% slippage
        )

        buy = result.trades[0]
        assert buy.price == pytest.approx(101.0)  # 100 * 1.01
        # qty sized against $500 budget at mid_price 100 -> 5 shares
        assert buy.qty == 5
        expected_cash = 1_000.0 - (5 * 101.0 + 2.0)
        assert result.ending_equity == pytest.approx(expected_cash + 5 * 100.0)

    def test_cash_never_goes_negative_under_aggressive_costs(self):
        """Regression test: size_and_validate sizes against mid_price,
        before slippage/commission are known. Under tight sizing (all cash
        committed) plus real slippage/commission, the naive fill cost can
        exceed available cash. The engine must trim quantity rather than
        let cash go negative."""
        dates = pd.bdate_range(start="2024-01-02", periods=1)
        strategy = ScriptedStrategy({("A", dates[0].strftime("%Y-%m-%d")): Action.BUY})
        price_data = {"A": make_ohlcv([100.0])}
        risk_manager = RiskManager(RiskLimits(max_position_pct=1.0, max_single_trade_pct=1.0))

        result = run_backtest(
            strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager,
            slippage_bps=100, commission_per_trade=5.0,  # 1% slippage + flat fee
        )

        buy = result.trades[0]
        cost = buy.qty * buy.price + 5.0
        assert cost <= 1_000.0 + 1e-9
        assert result.ending_equity >= 0


class TestDailyLossHaltIntegration:
    def test_unrealized_loss_halts_new_buy_same_day(self):
        """Regression test for the risk manager's mark-to-market fix:
        symbol A is bought on day 1 with most of the portfolio. On day 2 it
        drops enough to breach the 3% *portfolio* daily loss limit on an
        unrealized basis alone (no sells have happened, realized_pnl_today
        stays 0) - but not enough to trip A's own -5% stop-loss. A fresh
        BUY signal on symbol B that same day must be rejected by the daily
        loss halt. Before the fix, this would have gone through, since the
        halt only looked at realized P&L."""
        dates = pd.bdate_range(start="2024-01-02", periods=2)
        day1, day2 = (d.strftime("%Y-%m-%d") for d in dates)

        strategy = ScriptedStrategy({
            ("A", day1): Action.BUY,
            ("B", day2): Action.BUY,
        })
        price_data = {
            "A": make_ohlcv([100.0, 96.0], start="2024-01-02"),   # -4% on day 2
            "B": make_ohlcv([50.0, 50.0], start="2024-01-02"),
        }
        risk_manager = RiskManager(RiskLimits(
            max_position_pct=0.9, max_single_trade_pct=0.9,
            max_daily_loss_pct=0.03, trailing_stop_pct=0.05, max_open_positions=8,
        ))

        result = run_backtest(strategy, price_data, starting_cash=10_000.0, risk_manager=risk_manager)

        symbols_traded = {t.symbol for t in result.trades}
        assert "A" in symbols_traded
        assert "B" not in symbols_traded, "B should have been rejected by the daily loss halt"
        # sanity: the loss was purely unrealized - nothing was sold to produce it
        assert all(t.action == "buy" for t in result.trades)
        # day 2 equity should reflect A's mark-to-market drop: 1000 cash + 90*96 = 9640
        assert result.equity_curve.iloc[-1] == pytest.approx(1_000.0 + 90 * 96.0)

    def test_no_halt_when_loss_stays_under_threshold(self):
        """Control case: same setup, but A only drops 1% - well under the
        3% portfolio limit - so B's buy should go through normally."""
        dates = pd.bdate_range(start="2024-01-02", periods=2)
        day1, day2 = (d.strftime("%Y-%m-%d") for d in dates)

        strategy = ScriptedStrategy({
            ("A", day1): Action.BUY,
            ("B", day2): Action.BUY,
        })
        price_data = {
            "A": make_ohlcv([100.0, 99.0], start="2024-01-02"),   # -1%
            "B": make_ohlcv([50.0, 50.0], start="2024-01-02"),
        }
        risk_manager = RiskManager(RiskLimits(
            max_position_pct=0.9, max_single_trade_pct=0.9,
            max_daily_loss_pct=0.03, trailing_stop_pct=0.05, max_open_positions=8,
        ))

        result = run_backtest(strategy, price_data, starting_cash=10_000.0, risk_manager=risk_manager)

        symbols_traded = {t.symbol for t in result.trades}
        assert symbols_traded == {"A", "B"}
