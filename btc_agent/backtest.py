"""
Backtest engine for the BTC-only service.

Single-asset, single-position version of the equity scaffold's engine.
Runs the strategy bar-by-bar against historical BTC-USD data, through the
same RiskManager that would gate live trades.

Known simplifications (same spirit as the equity scaffold - be aware of
these before trusting results):
  - Fills happen at the same bar's close, not the next bar's open
  - Slippage and commission only apply if passed in (both default to 0)
  - No partial fills, no market-impact modeling
  - Works on whatever bar granularity price_data is in (daily or intraday -
    see data.py's load_btc_history vs. load_btc_intraday_history). A
    strategy targeting sub-1% moves still only gets checked once per bar,
    so it cannot see a touch of its target that reverses within the same
    bar - use finer bars if that matters for a given strategy.
  - "Trading day" boundaries (for the daily loss halt) are calendar-day
    based, since crypto has no exchange open/close to anchor to. This
    still works with intraday bars - it just resets once per day rather
    than once per bar.
"""

from dataclasses import dataclass, field

import pandas as pd

from btc_agent.risk import PortfolioState, RiskManager, TradeRejected
from btc_agent.strategy import Action


@dataclass
class Trade:
    date: pd.Timestamp
    action: str
    qty: float
    price: float
    reason: str


@dataclass
class BacktestResult:
    trades: list = field(default_factory=list)
    equity_curve: pd.Series = None
    starting_equity: float = 0.0
    ending_equity: float = 0.0

    @property
    def total_return_pct(self) -> float:
        if self.starting_equity == 0:
            return 0.0
        return (self.ending_equity - self.starting_equity) / self.starting_equity * 100

    @property
    def max_drawdown_pct(self) -> float:
        if self.equity_curve is None or self.equity_curve.empty:
            return 0.0
        running_max = self.equity_curve.cummax()
        drawdown = (self.equity_curve - running_max) / running_max
        return drawdown.min() * 100

    def summary(self) -> str:
        return (
            f"Starting equity: ${self.starting_equity:,.2f}\n"
            f"Ending equity:   ${self.ending_equity:,.2f}\n"
            f"Total return:    {self.total_return_pct:.2f}%\n"
            f"Max drawdown:    {self.max_drawdown_pct:.2f}%\n"
            f"Total trades:    {len(self.trades)}"
        )


def run_backtest(
    strategy,
    price_data: pd.DataFrame,      # OHLCV, indexed by date
    starting_cash: float = 2_000.0,
    risk_manager: RiskManager = None,
    slippage_bps: float = 0.0,
    commission_per_trade: float = 0.0,
) -> BacktestResult:
    risk_manager = risk_manager or RiskManager()
    state = PortfolioState(equity=starting_cash, cash=starting_cash)
    if len(price_data) > 0:
        state.trading_day = price_data.index[0].date()
    trades = []
    equity_curve = []

    def fill_price(mid_price: float, side: str) -> float:
        slip = mid_price * (slippage_bps / 10_000)
        return mid_price + slip if side == "buy" else mid_price - slip

    def mark_to_market(price: float) -> None:
        holdings_value = state.position["qty"] * price if state.position else 0.0
        state.equity = state.cash + holdings_value

    def close_position(current_date, price: float, reason: str) -> None:
        pos = state.position
        state.position = None
        fill = fill_price(price, "sell")
        proceeds = pos["qty"] * fill - commission_per_trade
        pnl = proceeds - pos["qty"] * pos["avg_price"]
        state.cash += proceeds
        state.realized_pnl_today += pnl
        trades.append(Trade(current_date, "sell", pos["qty"], fill, reason))

    for current_date, row in price_data.iterrows():
        price = row["close"]

        if current_date.date() != state.trading_day:
            state.trading_day = current_date.date()
            state.realized_pnl_today = 0.0
            state.equity_at_day_start = state.equity

        # 1. Trailing stop, unconditional, before the strategy gets a say
        if risk_manager.check_trailing_stop(state, price):
            close_position(current_date, price, "trailing stop")

        # Mark-to-market before sizing new trades, so daily_loss_breached
        # (used inside size_and_validate) sees today's move already.
        mark_to_market(price)

        # 2. Strategy signal, once enough history has accumulated
        history = price_data.loc[:current_date]
        if len(history) >= strategy.min_bars_required():
            signal = strategy.generate_signal(history)

            if signal.action == Action.BUY:
                try:
                    qty = risk_manager.size_and_validate(signal, state, price)
                except TradeRejected:
                    qty = 0.0
                if qty > 0:
                    # size_and_validate sizes against mid_price, before
                    # slippage/commission are known - re-check against the
                    # actual fill cost so cash can't go negative.
                    fill = fill_price(price, "buy")
                    cost = qty * fill + commission_per_trade
                    if cost > state.cash:
                        qty = max(state.cash - commission_per_trade, 0.0) / fill
                        cost = qty * fill + commission_per_trade
                if qty > 0:
                    state.cash -= cost
                    state.position = {"qty": qty, "avg_price": fill, "peak_price": fill}
                    trades.append(Trade(current_date, "buy", qty, fill, signal.reason))

            elif signal.action == Action.SELL and state.position is not None:
                close_position(current_date, price, signal.reason)

        # 3. Mark-to-market for the day, now including today's trades
        mark_to_market(price)
        equity_curve.append((current_date, state.equity))

    curve = pd.Series(dict(equity_curve)).sort_index()
    return BacktestResult(
        trades=trades,
        equity_curve=curve,
        starting_equity=starting_cash,
        ending_equity=state.equity,
    )
