"""Integration tests for backtest.py against small constructed price series
with a scripted strategy, so behavior is fully deterministic."""

import pandas as pd
import pytest

from btc_agent.backtest import run_backtest
from btc_agent.risk import RiskLimits, RiskManager
from btc_agent.strategy import Action, Signal


def make_ohlcv(closes: list[float]) -> pd.DataFrame:
    dates = pd.date_range("2024-01-01", periods=len(closes), freq="D")
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes,
         "volume": [1_000] * len(closes)},
        index=dates,
    )


class ScriptedStrategy:
    """Returns a specific Action per date from a fixed script, HOLD
    otherwise - lets a test dictate exactly when a signal fires."""

    name = "scripted_test_strategy"

    def __init__(self, script: dict):
        self.script = script  # {"YYYY-MM-DD": Action}

    def min_bars_required(self) -> int:
        return 1

    def generate_signal(self, data: pd.DataFrame) -> Signal:
        date_str = data.index[-1].strftime("%Y-%m-%d")
        action = self.script.get(date_str, Action.HOLD)
        return Signal(action=action, strength=1.0, reason="scripted")


class TestBasicFlow:
    def test_buy_and_hold_produces_expected_equity(self):
        dates = pd.date_range("2024-01-01", periods=3, freq="D")
        strategy = ScriptedStrategy({dates[0].strftime("%Y-%m-%d"): Action.BUY})
        price_data = make_ohlcv([50_000.0, 50_000.0, 50_000.0])
        risk_manager = RiskManager(RiskLimits(max_position_pct=1.0))

        result = run_backtest(strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager)

        assert len(result.trades) == 1
        assert result.trades[0].action == "buy"
        assert result.trades[0].qty == pytest.approx(0.02)  # $1000 / $50,000
        assert result.ending_equity == pytest.approx(1_000.0)
        assert len(result.equity_curve) == 3

    def test_trailing_stop_forces_exit_regardless_of_strategy_signal(self):
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        strategy = ScriptedStrategy({dates[0].strftime("%Y-%m-%d"): Action.BUY})
        price_data = make_ohlcv([50_000.0, 44_000.0])  # -12%, past the 10% trailing stop
        risk_manager = RiskManager(RiskLimits(max_position_pct=1.0, trailing_stop_pct=0.10))

        result = run_backtest(strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager)

        assert [t.action for t in result.trades] == ["buy", "sell"]
        assert result.trades[1].reason == "trailing stop"
        assert result.trades[1].price == pytest.approx(44_000.0)

    def test_rally_lets_position_run_past_old_fixed_target_level(self):
        """No fixed take-profit: a position up 50% with no pullback stays open."""
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        strategy = ScriptedStrategy({dates[0].strftime("%Y-%m-%d"): Action.BUY})
        price_data = make_ohlcv([50_000.0, 75_000.0])  # +50%
        risk_manager = RiskManager(RiskLimits(max_position_pct=1.0, trailing_stop_pct=0.10))

        result = run_backtest(strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager)

        assert [t.action for t in result.trades] == ["buy"]
        assert result.ending_equity == pytest.approx(1_500.0)


class TestCostsModeling:
    def test_slippage_and_commission_applied_to_buy_fill(self):
        dates = pd.date_range("2024-01-01", periods=1, freq="D")
        strategy = ScriptedStrategy({dates[0].strftime("%Y-%m-%d"): Action.BUY})
        price_data = make_ohlcv([50_000.0])
        risk_manager = RiskManager(RiskLimits(max_position_pct=1.0))

        result = run_backtest(
            strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager,
            slippage_bps=100, commission_per_trade=2.0,  # 1% slippage
        )

        buy = result.trades[0]
        assert buy.price == pytest.approx(50_500.0)  # 50,000 * 1.01
        assert buy.qty == pytest.approx(998.0 / 50_500.0)  # ($1000 - $2 commission) / fill price
        assert result.ending_equity >= 0

    def test_cash_never_goes_negative_under_aggressive_costs(self):
        dates = pd.date_range("2024-01-01", periods=1, freq="D")
        strategy = ScriptedStrategy({dates[0].strftime("%Y-%m-%d"): Action.BUY})
        price_data = make_ohlcv([50_000.0])
        risk_manager = RiskManager(RiskLimits(max_position_pct=1.0))

        result = run_backtest(
            strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager,
            slippage_bps=100, commission_per_trade=5.0,
        )

        buy = result.trades[0]
        cost = buy.qty * buy.price + 5.0
        assert cost <= 1_000.0 + 1e-9
        assert result.ending_equity >= 0


class TestDailyLossHalt:
    def test_same_day_rebuy_after_stop_loss_is_halted_by_daily_loss(self):
        """Day 1: buy at 50k. Day 2: price craters to 40k, tripping the 10%
        trailing stop and realizing a -20% day - which also breaches the 5%
        daily loss limit. The strategy is scripted to try to re-buy that
        same bar; by then the position is already flat (closed by the
        trailing stop, not "already holding"), so this isolates the daily
        loss halt specifically as what blocks the re-entry."""
        dates = pd.date_range("2024-01-01", periods=2, freq="D")
        day1, day2 = (d.strftime("%Y-%m-%d") for d in dates)
        strategy = ScriptedStrategy({day1: Action.BUY, day2: Action.BUY})
        price_data = make_ohlcv([50_000.0, 40_000.0])

        risk_manager = RiskManager(RiskLimits(
            max_position_pct=1.0, trailing_stop_pct=0.10, max_daily_loss_pct=0.05,
        ))
        result = run_backtest(strategy, price_data, starting_cash=1_000.0, risk_manager=risk_manager)

        assert [t.action for t in result.trades] == ["buy", "sell"]
        assert result.trades[1].reason == "trailing stop"
        assert result.ending_equity == pytest.approx(800.0)
