"""
Optional sentiment veto gates for new BUY intents: one per-symbol, one
portfolio-wide (macro).

Both are deliberately narrow, mirroring how risk/risk_manager.py works: a
hard yes/no check that can block a trade, not a score that resizes it.
Unlike the risk manager (which is always active), these gates are off by
default and only engage if explicitly enabled in config.yaml - headline
sentiment is a much noisier signal than the risk manager's hard portfolio
limits, so it shouldn't be silently on.

Only ever gate BUY intents. SELL intents - especially stop-loss/take-profit
exits from the risk manager - must never be blocked by sentiment: an exit
existing to protect capital shouldn't be second-guessed by a headline.

The macro gate is checked first and is the more severe of the two: a
risk-off macro tape blocks every symbol's BUY, not just one.
"""

from dataclasses import dataclass


class TradeVetoed(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass
class NewsFilterConfig:
    enabled: bool = False
    veto_sentiment_threshold: float = -0.2   # veto a BUY when the symbol's sentiment_score <= this


@dataclass
class MacroFilterConfig:
    enabled: bool = False
    veto_sentiment_threshold: float = -0.3   # veto ALL BUYs when market-wide sentiment_score <= this


def check_buy_veto(context: dict, config: NewsFilterConfig) -> None:
    """Raises TradeVetoed if `context` (as built by news.context.build_context)
    shows sentiment at or below the configured threshold. No-op if the gate
    is disabled."""
    if not config.enabled:
        return
    score = context.get("sentiment_score", 0.0)
    if score <= config.veto_sentiment_threshold:
        raise TradeVetoed(
            f"sentiment {context.get('sentiment_label', '?')} "
            f"({score:.3f}) at/below veto threshold {config.veto_sentiment_threshold}"
        )


def check_macro_veto(market_context: dict, config: MacroFilterConfig) -> None:
    """Raises TradeVetoed if `market_context` (as built by
    news.market_news.build_market_context) shows market-wide sentiment at
    or below the configured threshold. No-op if the gate is disabled or no
    market context was fetched."""
    if not config.enabled or not market_context:
        return
    score = market_context.get("sentiment_score", 0.0)
    if score <= config.veto_sentiment_threshold:
        raise TradeVetoed(
            f"macro sentiment {market_context.get('sentiment_label', '?')} "
            f"({score:.3f}) at/below veto threshold {config.veto_sentiment_threshold} - risk-off"
        )
