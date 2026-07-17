"""
Backtest engine.

Simulates a strategy bar-by-bar against historical data, running every
signal through the same RiskManager that would gate live trades. This is
intentional: your backtest should exercise the exact same risk logic you'll
trade with, or the backtest is lying to you about what live trading will
look like.

Known simplifications (be aware of these before trusting results):
  - Fills happen at the same bar's close, not the next bar's open
  - Slippage and commission are modeled only if you pass `slippage_bps` /
    `commission_per_trade` to `run_backtest` (both default to 0)
  - No partial fills, no market-impact modeling
  - Single-symbol position sizing does not account for correlation across
    multiple simultaneous positions
"""

from dataclasses import dataclass, field

import pandas as pd

from risk.risk_manager import PortfolioState, RiskManager, TradeRejected
from strategies.base import Action, Strategy


@dataclass
class Trade:
    date: pd.Timestamp
    symbol: str
    action: str
    qty: int
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

    @property
    def win_rate_pct(self) -> float:
        sells = [t for t in self.trades if t.action == "sell"]
        if not sells:
            return 0.0
        # crude win/loss: relies on trade log pairing done by caller if needed
        return float("nan")  # placeholder - see README for a note on this

    def summary(self) -> str:
        return (
            f"Starting equity: ${self.starting_equity:,.2f}\n"
            f"Ending equity:   ${self.ending_equity:,.2f}\n"
            f"Total return:    {self.total_return_pct:.2f}%\n"
            f"Max drawdown:    {self.max_drawdown_pct:.2f}%\n"
            f"Total trades:    {len(self.trades)}"
        )


def run_backtest(
    strategy: Strategy,
    price_data: dict,          # symbol -> DataFrame(OHLCV, indexed by date)
    starting_cash: float = 10_000.0,
    risk_manager: RiskManager = None,
    slippage_bps: float = 0.0,     # fill price moves against you by this many bps
    commission_per_trade: float = 0.0,   # flat fee charged on every buy and sell
) -> BacktestResult:
    risk_manager = risk_manager or RiskManager()
    symbols = list(price_data.keys())
    all_dates = sorted(set().union(*[df.index for df in price_data.values()]))

    state = PortfolioState(equity=starting_cash, cash=starting_cash)
    if all_dates:
        state.trading_day = all_dates[0].date()
    trades = []
    equity_curve = []

    def fill_price(mid_price: float, side: str) -> float:
        slip = mid_price * (slippage_bps / 10_000)
        return mid_price + slip if side == "buy" else mid_price - slip

    def mark_to_market(current_prices: dict) -> None:
        holdings_value = sum(
            pos["qty"] * current_prices.get(sym, pos["avg_price"])
            for sym, pos in state.positions.items()
        )
        state.equity = state.cash + holdings_value

    for current_date in all_dates:
        current_prices = {}
        for symbol in symbols:
            df = price_data[symbol]
            if current_date not in df.index:
                continue
            current_prices[symbol] = df.loc[current_date, "close"]

        # New trading day: snapshot yesterday's close equity as today's
        # baseline for daily_loss_breached, and reset realized_pnl_today.
        if current_date.date() != state.trading_day:
            state.trading_day = current_date.date()
            state.realized_pnl_today = 0.0
            state.equity_at_day_start = state.equity

        # 1. Enforce stop losses / take profits first, unconditionally
        for symbol in risk_manager.check_stop_losses(state, current_prices):
            pos = state.positions.pop(symbol)
            price = fill_price(current_prices[symbol], "sell")
            proceeds = pos["qty"] * price - commission_per_trade
            pnl = proceeds - pos["qty"] * pos["avg_price"]
            state.cash += proceeds
            state.realized_pnl_today += pnl
            trades.append(Trade(current_date, symbol, "sell", pos["qty"],
                                 price, "stop-loss/take-profit"))

        # Mark-to-market on today's prices *before* sizing new trades, so
        # daily_loss_breached (called from size_and_validate below) sees
        # today's unrealized moves on still-open positions, not yesterday's
        # stale equity. See risk_manager.daily_loss_breached's docstring.
        mark_to_market(current_prices)

        # 2. Run the strategy per symbol, bar data truncated to "now"
        for symbol in symbols:
            df = price_data[symbol]
            if current_date not in df.index:
                continue
            history = df.loc[:current_date]
            if len(history) < strategy.min_bars_required():
                continue

            signal = strategy.generate_signal(symbol, history)
            mid_price = current_prices[symbol]

            if signal.action == Action.BUY:
                try:
                    qty = risk_manager.size_and_validate(signal, state, mid_price)
                except TradeRejected:
                    continue
                if qty > 0:
                    # size_and_validate sizes against mid_price, before
                    # slippage/commission are known - re-check affordability
                    # against the actual fill cost so cash can't go negative
                    # (a real broker would reject/trim an order that
                    # exceeds buying power; this mirrors that).
                    price = fill_price(mid_price, "buy")
                    cost = qty * price + commission_per_trade
                    if cost > state.cash:
                        qty = int((state.cash - commission_per_trade) // price)
                        cost = qty * price + commission_per_trade
                if qty > 0:
                    state.cash -= cost
                    state.positions[symbol] = {"qty": qty, "avg_price": price}
                    trades.append(Trade(current_date, symbol, "buy", qty, price, signal.reason))

            elif signal.action == Action.SELL and symbol in state.positions:
                pos = state.positions.pop(symbol)
                price = fill_price(mid_price, "sell")
                proceeds = pos["qty"] * price - commission_per_trade
                pnl = proceeds - pos["qty"] * pos["avg_price"]
                state.cash += proceeds
                state.realized_pnl_today += pnl
                trades.append(Trade(current_date, symbol, "sell", pos["qty"], price, signal.reason))

        # 3. Mark-to-market equity for the day, now including today's trades
        mark_to_market(current_prices)
        equity_curve.append((current_date, state.equity))

    curve = pd.Series(dict(equity_curve)).sort_index()
    return BacktestResult(
        trades=trades,
        equity_curve=curve,
        starting_equity=starting_cash,
        ending_equity=state.equity,
    )
