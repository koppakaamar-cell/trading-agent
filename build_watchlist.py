"""
Builds TODAY's candidate watchlist for live/paper trading by screening a
live, non-hardcoded pool of liquid/active stocks (via Yahoo Finance's
screeners) on volatility band, earnings proximity, news sentiment, and
pairwise correlation.

IMPORTANT: This is for the live/paper flow only. Do NOT copy its output
into config.yaml's `watchlist:` and then run a historical backtest against
it - selecting symbols using today's characteristics and backtesting them
over past history is lookahead/survivorship bias. run_backtest.py
intentionally keeps its own fixed watchlist for that reason. See
universe/screen.py and README.md.

Usage:
    python build_watchlist.py
"""

import yaml

from universe.candidates import get_candidate_symbols
from universe.screen import UniverseCriteria, select_watchlist


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    cfg = load_config()
    ucfg = cfg.get("universe", {})

    screeners = ucfg.get("screeners", ["most_actives", "day_gainers", "growth_technology_stocks"])
    count_per_screener = ucfg.get("candidates_per_screener", 25)

    print(f"Pulling candidates from screeners: {screeners}...")
    candidates = get_candidate_symbols(screeners=screeners, count_per_screener=count_per_screener)
    print(f"{len(candidates)} unique candidates before filtering.")

    criteria = UniverseCriteria(
        max_symbols=ucfg.get("max_symbols", 10),
        min_price=ucfg.get("min_price", 5.0),
        min_avg_volume=ucfg.get("min_avg_volume", 1_000_000),
        min_annualized_volatility=ucfg.get("min_annualized_volatility", 0.15),
        max_annualized_volatility=ucfg.get("max_annualized_volatility", 0.80),
        min_days_to_earnings=ucfg.get("min_days_to_earnings", 3),
        min_sentiment_score=ucfg.get("min_sentiment_score", -0.2),
        max_correlation=ucfg.get("max_correlation", 0.7),
    )

    print("Screening on liquidity, volatility band, earnings proximity, sentiment, and correlation...")
    selected = select_watchlist(candidates, criteria)

    print(f"\n=== Selected watchlist ({len(selected)} symbols) ===")
    for c in selected:
        print(
            f"{c['symbol']:6s} score={c['score']:.3f}  "
            f"price=${c['price']:.2f}  vol3m={c['avg_volume_3m']:,}  "
            f"ann.volatility={c['annualized_volatility']:.2%}  "
            f"sentiment={c['sentiment_score']:+.3f}  "
            f"next_earnings={c['next_earnings_date'] or 'n/a'}"
        )

    if selected:
        print("\nFor live/paper trading, use this as your watchlist:")
        print([c["symbol"] for c in selected])
    else:
        print("\nNo candidates passed all filters - try loosening universe.* criteria in config.yaml.")


if __name__ == "__main__":
    main()
