"""
Pulls a live, non-hardcoded candidate pool from Yahoo Finance's predefined
screeners (via yfinance's free `yf.screen`, no API key). This is the raw
pool - liquidity/volatility/earnings/sentiment filtering and ranking
happens in universe/screen.py.

Run `python -c "import yfinance as yf; print(yf.PREDEFINED_SCREENER_QUERIES.keys())"`
to see the full list of available screeners (day_losers, most_shorted_stocks,
undervalued_large_caps, etc.) if you want to change the mix.
"""

import yfinance as yf

DEFAULT_SCREENERS = ["most_actives", "day_gainers", "growth_technology_stocks"]


def get_candidate_symbols(
    screeners: list[str] = None, count_per_screener: int = 25
) -> dict:
    """Returns {symbol: {price, avg_volume_3m, market_cap}}, deduped across
    the given screeners. Best-effort: a screener that fails to fetch is
    silently skipped rather than aborting the whole pool."""
    screeners = screeners or DEFAULT_SCREENERS
    candidates = {}
    for name in screeners:
        try:
            res = yf.screen(name, count=count_per_screener)
        except Exception:
            continue
        for q in res.get("quotes", []):
            symbol = q.get("symbol")
            if not symbol:
                continue
            candidates[symbol] = {
                "price": q.get("regularMarketPrice"),
                "avg_volume_3m": q.get("averageDailyVolume3Month"),
                "market_cap": q.get("marketCap"),
            }
    return candidates
