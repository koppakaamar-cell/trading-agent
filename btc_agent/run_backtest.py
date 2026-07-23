"""
Run a backtest of the BTC momentum strategy against real BTC-USD history.

Usage (from this directory):
    python run_backtest.py                  # real data, last 2 years
    python run_backtest.py --years 5         # real data, last 5 years
"""

import argparse
import datetime as dt
import sys
from pathlib import Path

# btc_agent is a package (see __init__.py) so its modules can be imported
# as btc_agent.X without colliding with the equity scaffold's top-level
# risk/ and backtest/ packages. That requires this directory's *parent* on
# sys.path, not this directory itself - add it so `python run_backtest.py`
# works when run directly from inside btc_agent/, same as before.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from btc_agent.backtest import run_backtest
from btc_agent.data import load_btc_history
from btc_agent.execution import build_order_intents_from_trades
from btc_agent.risk import RiskLimits, RiskManager
from btc_agent.strategy import MomentumStrategy


def load_config(path: str = "config.yaml") -> dict:
    with open(Path(__file__).resolve().parent / path) as f:
        return yaml.safe_load(f)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=2,
                         help="years of real history to pull (default: 2)")
    args = parser.parse_args()

    cfg = load_config()
    symbol = cfg["symbol"]

    strategy = MomentumStrategy(**cfg["strategy"]["params"])
    risk_manager = RiskManager(RiskLimits(**cfg["risk"]))

    end = dt.date.today()
    start = end - dt.timedelta(days=365 * args.years)
    print(f"Fetching {args.years}y of real history for {symbol}...")
    price_data = load_btc_history(symbol, start=start.isoformat(), end=end.isoformat())
    if price_data.empty:
        raise SystemExit(f"No data returned for {symbol}.")

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
        print(f"{t.date.date()} {t.action.upper():4s} {t.qty:.6f} {symbol} @ ${t.price:,.2f}  ({t.reason})")

    intents = build_order_intents_from_trades(result.trades[-3:], strategy.name, symbol)
    print("\n--- Sample order intents (for Claude Code to review via MCP, once crypto tools are confirmed) ---")
    for intent in intents:
        print(intent.to_log_line())


if __name__ == "__main__":
    main()
