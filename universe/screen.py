"""
Screens a raw candidate pool (universe.candidates.get_candidate_symbols)
down to a final watchlist, filtering on liquidity, volatility band,
earnings proximity, and news sentiment, then ranking and greedily
selecting while capping pairwise correlation so the result isn't just
five versions of the same trade.

IMPORTANT - lookahead/survivorship bias warning:
This reflects TODAY's liquidity, volatility, sentiment, and earnings
calendar. Do NOT feed its output into run_backtest.py's historical
watchlist - selecting symbols using today's characteristics and then
backtesting them over past history would test the strategy on a universe
chosen with information that didn't exist at those historical dates,
flattering the backtest in a way that won't hold up live. Use this only
to build a watchlist for the live/paper flow (see build_watchlist.py);
run_backtest.py intentionally keeps its own fixed `watchlist:` in
config.yaml.
"""

import datetime as dt
from dataclasses import dataclass

import pandas as pd
import yfinance as yf

from news.news_provider import get_headlines, get_next_earnings_date
from news.sentiment import score_headlines


@dataclass
class UniverseCriteria:
    max_symbols: int = 10
    min_price: float = 5.0
    min_avg_volume: int = 1_000_000
    min_annualized_volatility: float = 0.15
    max_annualized_volatility: float = 0.80
    min_days_to_earnings: int = 3       # exclude candidates with earnings sooner than this
    min_sentiment_score: float = -0.2   # exclude candidates more negative than this
    max_correlation: float = 0.7        # cap pairwise return correlation among selected picks


def _liquidity_filter(candidates: dict, criteria: UniverseCriteria) -> dict:
    out = {}
    for symbol, info in candidates.items():
        price, volume = info.get("price"), info.get("avg_volume_3m")
        if price is None or volume is None:
            continue
        if price < criteria.min_price or volume < criteria.min_avg_volume:
            continue
        out[symbol] = info
    return out


def _fetch_closes(symbols: list[str], period: str = "4mo") -> dict:
    """Batch-downloads recent daily bars for all symbols in one request.
    Returns {symbol: close_series}, dropping symbols with too little
    history to compute volatility/correlation on."""
    if not symbols:
        return {}
    raw = yf.download(symbols, period=period, progress=False, group_by="ticker")
    out = {}
    for symbol in symbols:
        try:
            closes = raw["Close"] if len(symbols) == 1 else raw[symbol]["Close"]
        except (KeyError, TypeError):
            continue
        closes = closes.dropna()
        if len(closes) >= 20:
            out[symbol] = closes
    return out


def _annualized_volatility(close: pd.Series) -> float:
    returns = close.pct_change().dropna()
    return returns.std() * (252 ** 0.5)


def _correlation(a: pd.Series, b: pd.Series) -> float:
    aligned = pd.concat([a.pct_change(), b.pct_change()], axis=1).dropna()
    if len(aligned) < 20:
        return 0.0
    corr = aligned.iloc[:, 0].corr(aligned.iloc[:, 1])
    return 0.0 if pd.isna(corr) else corr


def select_watchlist(candidates: dict, criteria: UniverseCriteria = None) -> list[dict]:
    """Filters and ranks `candidates` down to at most criteria.max_symbols
    symbols. Returns a list of dicts (symbol, score, and the underlying
    metrics) ordered best-first, with each addition checked against the
    correlation cap against everything already selected."""
    criteria = criteria or UniverseCriteria()

    liquid = _liquidity_filter(candidates, criteria)
    if not liquid:
        return []

    symbols = list(liquid.keys())
    closes = _fetch_closes(symbols)

    band_mid = (criteria.min_annualized_volatility + criteria.max_annualized_volatility) / 2
    band_half_width = (criteria.max_annualized_volatility - criteria.min_annualized_volatility) / 2

    scored = []
    for symbol in symbols:
        close = closes.get(symbol)
        if close is None:
            continue

        vol = _annualized_volatility(close)
        if not (criteria.min_annualized_volatility <= vol <= criteria.max_annualized_volatility):
            continue

        earnings_date = get_next_earnings_date(symbol)
        if earnings_date:
            days_to_earnings = (earnings_date - dt.date.today()).days
            if 0 <= days_to_earnings < criteria.min_days_to_earnings:
                continue

        sentiment = score_headlines(get_headlines(symbol, limit=5))
        if sentiment < criteria.min_sentiment_score:
            continue

        # Composite score: reward liquidity and positive sentiment, and
        # reward volatility near the middle of the target band (a proxy
        # for "has real moves without being unhinged").
        volatility_fit = 1 - abs(vol - band_mid) / band_half_width if band_half_width > 0 else 0.5
        liquidity_score = min(liquid[symbol]["avg_volume_3m"] / 10_000_000, 1.0)
        score = 0.4 * liquidity_score + 0.3 * volatility_fit + 0.3 * ((sentiment + 1) / 2)

        scored.append({
            "symbol": symbol,
            "score": round(score, 4),
            "price": liquid[symbol]["price"],
            "avg_volume_3m": liquid[symbol]["avg_volume_3m"],
            "annualized_volatility": round(vol, 4),
            "sentiment_score": round(sentiment, 4),
            "next_earnings_date": earnings_date.isoformat() if earnings_date else None,
            "_close": close,
        })

    scored.sort(key=lambda c: c["score"], reverse=True)

    selected = []
    for candidate in scored:
        if len(selected) >= criteria.max_symbols:
            break
        if any(_correlation(candidate["_close"], picked["_close"]) >= criteria.max_correlation
               for picked in selected):
            continue
        selected.append(candidate)

    for c in selected:
        del c["_close"]
    return selected
