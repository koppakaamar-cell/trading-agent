"""
Order intent builder for the BTC-only service.

Same architecture boundary as the equity scaffold: this code does NOT call
the Robinhood MCP server. It only decides WHAT trade the strategy+risk
layer wants and hands back an OrderIntent for Claude Code (with the
Robinhood connector attached) to review and submit.

UNCONFIRMED: the equity scaffold's README documents `review_equity_order`
and `place_equity_order` as real tool names on Robinhood's Agentic Trading
MCP server. Whether that server exposes crypto-specific tools (e.g.
something like `review_crypto_order` / `place_crypto_order`), or crypto
trades through the same equity-shaped tools with a crypto symbol, is NOT
confirmed - there's no evidence either way in what's documented so far.
Confirm the actual tool names and argument shapes in a live Claude Code
session with the connector attached before wiring this up for real, and
update `to_mcp_args` accordingly. Until then, treat mode: paper/live in
config.yaml as not actually functional for this service.

The flow, once confirmed:
  1. strategy + risk manager decide WHAT to do -> OrderIntent
  2. Claude Code calls the (TBD) review tool first, always, to preview
     fees/impact - never skip straight to placing an order
  3. Only after explicit confirmation does Claude call the (TBD) place
     tool. Nothing executes automatically.
"""

from dataclasses import dataclass, asdict, field
import json


@dataclass
class OrderIntent:
    symbol: str            # e.g. "BTC-USD" for backtesting; confirm Robinhood
                            # crypto's own symbol format before live use
    side: str               # "buy" or "sell"
    quantity: float          # fractional - BTC trades in fractions of a coin
    order_type: str = "market"   # or "limit"
    limit_price: float | None = None
    reason: str = ""
    strategy_name: str = ""
    context: dict = field(default_factory=dict)

    def to_mcp_args(self) -> dict:
        """UNCONFIRMED shape - see module docstring. This mirrors the
        equity scaffold's guessed shape; do not trust it against the real
        tool schema without checking first."""
        args = {
            "symbol": self.symbol,
            "side": self.side,
            "quantity": self.quantity,
            "order_type": self.order_type,
        }
        if self.limit_price is not None:
            args["limit_price"] = self.limit_price
        return args

    def to_log_line(self) -> str:
        return json.dumps(asdict(self))


def build_order_intents_from_trades(trades, strategy_name: str, symbol: str) -> list[OrderIntent]:
    """Convert backtest/live Trade objects (see backtest.py) into
    OrderIntents ready for Claude Code to review and submit."""
    return [
        OrderIntent(
            symbol=symbol,
            side=t.action,
            quantity=t.qty,
            reason=t.reason,
            strategy_name=strategy_name,
        )
        for t in trades
    ]
