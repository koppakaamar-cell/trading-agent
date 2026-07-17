"""
Broad market / macro news - not tied to any single symbol. Pulls headlines
for major index tickers (S&P 500, Dow, Nasdaq, VIX) via yfinance, which in
practice surfaces Fed/rates decisions, broad selloffs or rallies, and
general risk-on/risk-off tone - the kind of thing that can matter more to
a trade than anything specific to the symbol itself.

Same free-data, current-only constraint as news/news_provider.py: this
can't be replayed historically, so (like news/) it's only meaningful for
the live/paper flow, not the backtest loop.
"""

import yfinance as yf

from news.sentiment import score_headlines, sentiment_label

DEFAULT_MACRO_SYMBOLS = ["^GSPC", "^DJI", "^IXIC", "^VIX"]


def get_market_headlines(symbols: list[str] = None, limit_per_symbol: int = 5) -> list[dict]:
    """Fetches headlines for each macro symbol and merges them, deduped by
    title, into a single list. Best-effort: a symbol that fails to fetch
    is silently skipped."""
    symbols = symbols or DEFAULT_MACRO_SYMBOLS
    seen_titles = set()
    headlines = []
    for symbol in symbols:
        try:
            raw = yf.Ticker(symbol).news or []
        except Exception:
            continue
        for item in raw[:limit_per_symbol]:
            content = item.get("content", {})
            title = content.get("title", "")
            if not title or title in seen_titles:
                continue
            seen_titles.add(title)
            headlines.append({
                "title": title,
                "summary": content.get("summary") or content.get("description", ""),
                "publisher": (content.get("provider") or {}).get("displayName", ""),
                "published": content.get("pubDate", ""),
                "source_symbol": symbol,
            })
    return headlines


def build_market_context(symbols: list[str] = None, limit_per_symbol: int = 5) -> dict:
    """Composes macro headlines + aggregate sentiment into a single
    market-wide snapshot, in the same shape as news.context.build_context
    but not scoped to any one symbol."""
    headlines = get_market_headlines(symbols=symbols, limit_per_symbol=limit_per_symbol)
    sentiment_score = score_headlines(headlines)
    return {
        "headlines": [
            {"title": h["title"], "publisher": h["publisher"], "source_symbol": h["source_symbol"]}
            for h in headlines
        ],
        "sentiment_score": round(sentiment_score, 3),
        "sentiment_label": sentiment_label(sentiment_score),
    }
