"""
Order intent builder.

IMPORTANT ARCHITECTURE NOTE:
This project does NOT call the Robinhood MCP server directly from Python.
MCP tools are called by the AI agent (Claude, inside Claude Code) that has
the Robinhood connector attached - not by arbitrary scripts. That's by
design: it keeps a human/Claude checkpoint between "the strategy wants to
trade" and "an order actually goes to the broker."

The flow is:
  1. Your Python code (strategy + risk manager + backtester) decides WHAT
     it wants to do and produces an OrderIntent.
  2. attach_news_context() (below) optionally attaches headlines/sentiment/
     fundamentals/macro market mood and, if enabled in config.yaml, runs
     the sentiment vetoes on BUY intents (see news/filter.py) - a
     portfolio-wide macro gate (risk-off tape blocks every symbol) checked
     before a per-symbol gate. These are a second and third, independent
     gate on top of the risk manager - all three can say no.
  3. Claude Code reads that OrderIntent and calls the Robinhood MCP tools:
       - Check intent.context["veto"]["vetoed"] first - if true, do not
         proceed, and relay the reason instead.
       - `review_equity_order` first, always, to preview fees/impact
       - `place_equity_order` only after you've confirmed you want to proceed
  4. Nothing executes without that explicit step. Do not build a shortcut
     that skips review_equity_order, even for "small" trades.

This file just defines the data shape so that boundary stays clean.
"""

from dataclasses import dataclass, asdict, field
import json


@dataclass
class OrderIntent:
    symbol: str
    side: str          # "buy" or "sell"
    quantity: int
    order_type: str = "market"   # or "limit"
    limit_price: float | None = None
    reason: str = ""
    strategy_name: str = ""
    # News/sentiment/fundamentals snapshot from news.context.build_context,
    # if attached via attach_news_context(). Includes a "market" sub-dict
    # (macro sentiment from news.market_news, if fetched) and a "veto"
    # sub-dict ({"vetoed": bool, "reason": str|None}) - besides the risk
    # manager, the only parts of this project that can say no to a trade.
    # See news/filter.py.
    context: dict = field(default_factory=dict)

    def to_mcp_args(self) -> dict:
        """Shape this roughly matches what place_equity_order likely expects.
        Confirm exact field names against the live tool schema in Claude Code
        (`get_equity_quotes`/`place_equity_order` docs) before relying on it -
        Robinhood's MCP schema was still thin on docs as of mid-2026."""
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


def attach_news_context(
    intent: OrderIntent,
    headline_limit: int = 5,
    filter_config=None,
    market_context: dict = None,
    macro_filter_config=None,
) -> OrderIntent:
    """Fetches current headlines/sentiment/fundamentals for intent.symbol
    and attaches them to intent.context. Only meaningful for intents built
    from the *current* bar (live/paper flow) - see news/context.py for why
    this can't be used inside the historical backtest loop.

    `market_context` (from news.market_news.build_market_context) is
    portfolio-wide, not per-symbol - fetch it once per run, not once per
    intent, and pass the same dict in for every intent to avoid redundant
    fetches.

    If `macro_filter_config` (news.filter.MacroFilterConfig) is enabled,
    checks the macro veto first - a risk-off market tape blocks every
    symbol's BUY, not just this one. Only if that passes does
    `filter_config` (news.filter.NewsFilterConfig) get checked for this
    symbol specifically. Neither ever vetoes SELL intents - see
    news/filter.py. Does not raise; check intent.context["veto"]["vetoed"]
    instead, so a caller can log/display the reason before deciding not to
    submit."""
    from news.context import build_context
    from news.filter import (
        MacroFilterConfig, NewsFilterConfig, TradeVetoed,
        check_buy_veto, check_macro_veto,
    )

    intent.context = build_context(intent.symbol, headline_limit=headline_limit)
    intent.context["market"] = market_context or {}
    filter_config = filter_config or NewsFilterConfig()
    macro_filter_config = macro_filter_config or MacroFilterConfig()

    veto = {"vetoed": False, "reason": None}
    if intent.side == "buy":
        try:
            check_macro_veto(market_context or {}, macro_filter_config)
            check_buy_veto(intent.context, filter_config)
        except TradeVetoed as e:
            veto = {"vetoed": True, "reason": e.reason}
    intent.context["veto"] = veto
    return intent


def build_order_intents_from_trades(trades, strategy_name: str) -> list[OrderIntent]:
    """Convert backtest/live Trade objects (see backtest/engine.py) into
    OrderIntents ready for Claude Code to review and submit."""
    intents = []
    for t in trades:
        intents.append(
            OrderIntent(
                symbol=t.symbol,
                side=t.action,
                quantity=t.qty,
                reason=t.reason,
                strategy_name=strategy_name,
            )
        )
    return intents
