"""
Risk manager for the BTC-only service.

Single asset, so this is a lot smaller than the equity scaffold's risk
manager: no multi-symbol position limits, no cross-symbol correlation
concerns, at most one open position ever. What it does keep: a trailing
stop (exits on pullback from peak rather than a fixed target, so a trend
can keep running) and a daily loss halt. Position sizing is fractional -
BTC trades in fractions of a coin, not whole shares.

This is the validated default (see README.md's backtest comparison table):
letting winners run via a trailing stop, rather than a fixed take-profit
or a tiny scalping target, was the only config tested that stayed
competitive with buy-and-hold's upside while cutting its drawdown
roughly in half. Change it deliberately, not as a one-off experiment -
if you do, re-run the backtest across multiple windows before trusting it.
"""

from dataclasses import dataclass, field
from datetime import date

from btc_agent.strategy import Action, Signal


@dataclass
class RiskLimits:
    trailing_stop_pct: float = 0.10
    max_daily_loss_pct: float = 0.05
    max_position_pct: float = 1.0    # % of equity a position may use (cash still the real cap)


@dataclass
class PortfolioState:
    equity: float
    cash: float
    position: dict = None            # {"qty": float, "avg_price": float, "peak_price": float} or None
    realized_pnl_today: float = 0.0
    equity_at_day_start: float = 0.0
    trading_day: date = field(default_factory=date.today)

    def __post_init__(self):
        if self.equity_at_day_start <= 0:
            self.equity_at_day_start = self.equity


class TradeRejected(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


class RiskManager:
    def __init__(self, limits: RiskLimits = None):
        self.limits = limits or RiskLimits()

    def daily_loss_breached(self, state: PortfolioState) -> bool:
        """Same realized+unrealized distinction as the equity scaffold:
        gates on total equity drawdown from the period's start, not just
        booked P&L, so a position bleeding unrealized loss still halts new
        entries."""
        if state.equity <= 0:
            return True
        if state.equity_at_day_start <= 0:
            return False
        loss_pct = (state.equity_at_day_start - state.equity) / state.equity_at_day_start
        return loss_pct >= self.limits.max_daily_loss_pct

    def check_trailing_stop(self, state: PortfolioState, current_price: float) -> bool:
        """Returns True if the open position (if any) has pulled back
        `trailing_stop_pct` from its peak price since entry and should be
        closed regardless of what the strategy says."""
        if state.position is None or current_price is None:
            return False
        peak = max(state.position.get("peak_price", state.position["avg_price"]), current_price)
        state.position["peak_price"] = peak
        drawdown_from_peak = (peak - current_price) / peak
        return drawdown_from_peak >= self.limits.trailing_stop_pct

    def size_and_validate(
        self, signal: Signal, state: PortfolioState, current_price: float
    ) -> float:
        """Given a BUY signal, returns the fractional BTC quantity to buy.
        Raises TradeRejected if the trade shouldn't happen at all. Returns
        0.0 for HOLD/SELL (nothing to size)."""
        if signal.action != Action.BUY:
            return 0.0

        if self.daily_loss_breached(state):
            raise TradeRejected("daily loss limit breached, no new positions today")

        if state.position is not None:
            raise TradeRejected("already holding a BTC position")

        if current_price <= 0:
            raise TradeRejected("invalid price")

        max_dollars = min(state.equity * self.limits.max_position_pct, state.cash)
        qty = max_dollars / current_price

        if qty <= 0:
            raise TradeRejected("position size rounds to 0")

        return qty
