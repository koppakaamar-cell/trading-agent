"""
Composes headlines + sentiment + fundamentals + next earnings date into a
single "why" snapshot for a symbol, meant to be attached to a Signal or
OrderIntent so a human (or Claude, reviewing via the Robinhood MCP tools)
can see market context alongside the price-based trade decision.

Purely informational - see execution/order_intent.py for how this plugs
into OrderIntent.context. Nothing here changes what the strategy or risk
manager decide.
"""

from news.news_provider import get_fundamentals, get_headlines, get_next_earnings_date
from news.sentiment import score_headlines, sentiment_label


def build_context(symbol: str, headline_limit: int = 5) -> dict:
    headlines = get_headlines(symbol, limit=headline_limit)
    sentiment_score = score_headlines(headlines)
    earnings_date = get_next_earnings_date(symbol)

    return {
        "headlines": [
            {"title": h["title"], "publisher": h["publisher"], "published": h["published"]}
            for h in headlines
        ],
        "sentiment_score": round(sentiment_score, 3),
        "sentiment_label": sentiment_label(sentiment_score),
        "next_earnings_date": earnings_date.isoformat() if earnings_date else None,
        "fundamentals": get_fundamentals(symbol),
    }
