"""
Run a backtest of the configured strategy against real historical data
(via yfinance) or synthetic data (as a smoke test / offline fallback).

Usage:
    python run_backtest.py                  # real data, last 2 years
    python run_backtest.py --years 5         # real data, last 5 years
    python run_backtest.py --synthetic       # synthetic random-walk smoke test
"""

import argparse
import datetime as dt

import yaml

from backtest.engine import run_backtest
from data.data_provider import load_from_yfinance
from data.synthetic import generate_synthetic_ohlcv
from execution.order_intent import attach_news_context, build_order_intents_from_trades
from news.filter import MacroFilterConfig, NewsFilterConfig
from news.market_news import build_market_context
from risk.risk_manager import RiskLimits, RiskManager
from strategies.momentum import MomentumStrategy


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def load_real_price_data(symbols: list[str], years: int) -> dict:
    end = dt.date.today()
    start = end - dt.timedelta(days=365 * years)
    price_data = {}
    for symbol in symbols:
        df = load_from_yfinance(symbol, start=start.isoformat(), end=end.isoformat())
        if df.empty:
            print(f"  warning: no data returned for {symbol}, skipping")
            continue
        price_data[symbol] = df
    return price_data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--synthetic", action="store_true",
                         help="use synthetic random-walk data instead of real history")
    parser.add_argument("--years", type=int, default=2,
                         help="years of real history to pull (default: 2)")
    parser.add_argument("--no-news", action="store_true",
                         help="skip attaching news/sentiment/fundamentals context to sample order intents")
    args = parser.parse_args()

    cfg = load_config()

    strategy = MomentumStrategy(**cfg["strategy"]["params"])
    risk_manager = RiskManager(RiskLimits(**cfg["risk"]))

    if args.synthetic:
        price_data = {
            symbol: generate_synthetic_ohlcv(symbol, days=300, seed=hash(symbol) % 1000)
            for symbol in cfg["watchlist"]
        }
    else:
        print(f"Fetching {args.years}y of real history for {cfg['watchlist']}...")
        price_data = load_real_price_data(cfg["watchlist"], args.years)
        if not price_data:
            raise SystemExit("No real data could be fetched. Try --synthetic instead.")

    costs = cfg.get("costs", {})
    result = run_backtest(
        strategy=strategy,
        price_data=price_data,
        starting_cash=cfg["account"]["starting_cash"],
        risk_manager=risk_manager,
        slippage_bps=costs.get("slippage_bps", 0.0),
        commission_per_trade=costs.get("commission_per_trade", 0.0),
    )

    print(f"\n=== Backtest: {strategy.name} ===")
    print(result.summary())

    print("\n--- Last 5 trades ---")
    for t in result.trades[-5:]:
        print(f"{t.date.date()} {t.action.upper():4s} {t.qty:>5d} {t.symbol:5s} @ ${t.price:.2f}  ({t.reason})")

    # Example of converting the most recent trades into order intents that
    # Claude Code would review/submit via the Robinhood MCP tools. News
    # context is only meaningful here (the "current" bar) - not inside the
    # historical backtest loop, since free news/fundamentals data is
    # current-only. See news/context.py.
    intents = build_order_intents_from_trades(result.trades[-3:], strategy.name)
    if not args.no_news:
        news_cfg = cfg.get("news", {})
        macro_cfg = news_cfg.get("macro", {})
        filter_config = NewsFilterConfig(
            enabled=news_cfg.get("enabled", False),
            veto_sentiment_threshold=news_cfg.get("veto_sentiment_threshold", -0.2),
        )
        macro_filter_config = MacroFilterConfig(
            enabled=macro_cfg.get("enabled", False),
            veto_sentiment_threshold=macro_cfg.get("veto_sentiment_threshold", -0.3),
        )

        print("\nFetching macro/market-wide news context...")
        market_context = build_market_context(symbols=macro_cfg.get("symbols"))
        print(f"  market sentiment: {market_context['sentiment_label']} ({market_context['sentiment_score']:+.3f})")

        print("Fetching news/sentiment/fundamentals context for sample intents...")
        intents = [
            attach_news_context(
                i,
                filter_config=filter_config,
                market_context=market_context,
                macro_filter_config=macro_filter_config,
            )
            for i in intents
        ]
    print("\n--- Sample order intents (for Claude Code to review via MCP) ---")
    for intent in intents:
        print(intent.to_log_line())
        veto = intent.context.get("veto") if intent.context else None
        if veto and veto["vetoed"]:
            print(f"  -> VETOED (would not be submitted): {veto['reason']}")


if __name__ == "__main__":
    main()
