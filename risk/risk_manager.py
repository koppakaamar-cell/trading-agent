"""
Risk manager.

This is the layer that actually keeps you solvent. Strategies can be wrong
often - that's normal - what matters is that no single mistake, or run of
mistakes, does outsized damage. Every rule here is a hard cap, not a
suggestion, and the RiskManager will REJECT a trade rather than resize it
into ambiguity.
"""

from dataclasses import dataclass, field
from datetime import date

from strategies.base import Action, Signal


@dataclass
class RiskLimits:
    max_position_pct: float = 1.0        # max % of portfolio in one symbol
    max_daily_loss_pct: float = 0.03      # halt trading for the day past this
    max_open_positions: int = 8
    trailing_stop_pct: float = 0.05       # exit if price falls this far from its peak since entry
    max_single_trade_pct: float = 1.0     # max % of portfolio in one order


@dataclass
class PortfolioState:
    equity: float
    cash: float
    positions: dict = field(default_factory=dict)   # symbol -> {qty, avg_price}
    realized_pnl_today: float = 0.0
    # Mark-to-market equity as of the start of the current trading day
    # (yesterday's close). Used by daily_loss_breached to catch *unrealized*
    # drawdown on open positions, not just booked/realized losses - see
    # daily_loss_breached's docstring for why that distinction matters.
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
        """
        Halts new positions once today's total mark-to-market loss (realized
        AND unrealized, i.e. equity_at_day_start -> current equity) hits the
        limit - not just realized_pnl_today.

        This distinction matters: realized_pnl_today only grows when a
        position is actually sold. On a day where open positions are
        bleeding hard but nothing has been sold yet, realized-only tracking
        would report zero loss and keep approving new buys straight into a
        falling market. Gating on total equity drawdown from the day's
        start closes that hole.
        """
        if state.equity <= 0:
            return True
        if state.equity_at_day_start <= 0:
            return False
        loss_pct = (state.equity_at_day_start - state.equity) / state.equity_at_day_start
        return loss_pct >= self.limits.max_daily_loss_pct

    def check_stop_losses(self, state: PortfolioState, current_prices: dict) -> list:
        """Returns list of symbols that have pulled back `trailing_stop_pct`
        from their peak price since entry (or from entry itself, if no new
        high has been made yet) and should be closed, regardless of what the
        strategy says.

        Trailing off the peak - rather than a fixed take-profit target -
        means a position that keeps making new highs is never force-closed
        for "being up enough"; it only exits once it actually gives back
        `trailing_stop_pct` from wherever it peaked. On day one that peak
        is the entry price, so this also acts as the initial stop-loss.
        """
        to_close = []
        for symbol, pos in state.positions.items():
            price = current_prices.get(symbol)
            if price is None:
                continue
            peak = max(pos.get("peak_price", pos["avg_price"]), price)
            pos["peak_price"] = peak
            drawdown_from_peak = (peak - price) / peak
            if drawdown_from_peak >= self.limits.trailing_stop_pct:
                to_close.append(symbol)
        return to_close

    def size_and_validate(
        self, signal: Signal, state: PortfolioState, current_price: float
    ) -> int:
        """
        Given a BUY signal, returns the number of shares to buy, respecting
        all limits. Raises TradeRejected if the trade shouldn't happen at all.
        Returns 0 for HOLD/SELL-with-no-position (nothing to size).
        """
        if signal.action != Action.BUY:
            return 0

        if self.daily_loss_breached(state):
            raise TradeRejected("daily loss limit breached, no new positions today")

        if len(state.positions) >= self.limits.max_open_positions:
            raise TradeRejected("max open positions reached")

        if signal.symbol in state.positions:
            raise TradeRejected("already holding a position in this symbol")

        if current_price <= 0:
            raise TradeRejected("invalid price")

        max_dollars = min(
            state.equity * self.limits.max_position_pct,
            state.equity * self.limits.max_single_trade_pct,
            state.cash,
        )
        qty = int(max_dollars // current_price)

        if qty <= 0:
            raise TradeRejected("position size rounds to 0 shares given current limits")

        return qty
