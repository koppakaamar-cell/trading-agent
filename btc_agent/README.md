# BTC-Only Trading Service

A standalone, single-asset sibling to the equity scaffold one level up.
Same spirit (backtest first, human/Claude checkpoint before any real
order), but its own codebase - not built by importing or subclassing the
equity project's `strategies/`/`risk/`/`backtest/`/`execution/` packages.

**This is not a ready-to-fund trading bot**, same disclaimer as the parent
project. Nothing here has been validated to make money; treat it as a
starting point to backtest, inspect, and improve.

## Why this exists as a separate thing

- **Different asset, different risk profile.** BTC moves more per day than
  a large-cap stock, trades 24/7 with no exchange calendar, and (unlike
  equities on a <$25k account) isn't subject to the Pattern Day Trader
  rule - so the constraints that shaped the equity scaffold's risk
  defaults don't directly apply here.
- **Fractional sizing.** One BTC costs tens of thousands of dollars, so
  position sizing here is a float (fractional coins), not `int(shares)`.
  The equity risk manager's integer-share rounding would be unusable.
- **Own account, own config.** `config.yaml` in this folder is independent
  of the parent project's - separate `starting_cash`, separate risk knobs.

## Layout

```
strategy.py    - MomentumStrategy: same dual-MA-crossover idea as the
                 equity scaffold, implemented fresh for a single symbol.
risk.py        - RiskManager: trailing stop (exit on pullback from peak,
                 not a fixed target - lets a trend keep running) + a daily
                 loss halt. At most one position ever (single asset), so
                 there's no multi-symbol position-limit logic to carry.
backtest.py    - Bar-by-bar single-asset backtest engine, fractional qty.
data.py        - BTC-USD daily bars via yfinance, for backtesting.
execution.py   - OrderIntent for Claude Code to review/submit via the
                 Robinhood MCP connector - see the warning below.
run_backtest.py - CLI entrypoint.
tests/         - pytest suite, no network calls.
```

`btc_agent` is a real Python package (`__init__.py`) so its modules import
as `btc_agent.risk`, `btc_agent.backtest`, etc. That's deliberate: flat
names like `risk` and `backtest` would collide with the equity scaffold's
own top-level `risk/` and `backtest/` packages if both test suites ran in
the same pytest session from the repo root.

## Robinhood crypto MCP connection - UNCONFIRMED

The equity scaffold's `.mcp.json` (one directory up) points Claude Code at
Robinhood's Agentic Trading MCP server, and its README documents
`review_equity_order` / `place_equity_order` as real tool names. Whether
that same server exposes crypto-specific tools, or handles crypto through
equity-shaped tools with a crypto symbol, **is not confirmed** - there's no
evidence either way yet. `execution.py`'s `to_mcp_args()` is a guess, not
a verified contract.

Before wiring `mode: paper` or `mode: live` up for real:
1. Connect the Robinhood MCP connector (same steps as the parent project's
   README) and actually inspect what crypto-related tools it exposes.
2. Update `execution.py::OrderIntent.to_mcp_args` to match the real schema.
3. Go through the parent project's "before you connect this to real money"
   checklist - it applies here too.

Until then, `mode` in `config.yaml` doesn't do anything - there's no live
loop implemented, same as the parent project.

## Getting started

```bash
pip install -r ../requirements.txt --break-system-packages   # yfinance, pandas, pyyaml
cd btc_agent
python run_backtest.py                # real BTC-USD data, last 2 years
python run_backtest.py --years 5       # last 5 years
```

## Current default: 20/50 MA crossover, 10% trailing stop, full capital

This is the config in `config.yaml` today. It's not "proven to make
money" - no strategy is, and treat anyone who claims otherwise with
suspicion - but it's the best *risk-adjusted* config actually tested
against real BTC-USD history in this project so far, including a direct
comparison against simply buying and holding:

| Window | Buy & hold | This strategy |
|---|---|---|
| 1 year | -46.53% (dd -53.06%) | -11.63% (dd -22.19%) |
| 2 years | -0.51% (dd -53.06%) | +38.96% (dd -22.19%) |
| 5 years | +100.62% (dd -76.63%) | +66.53% (dd -41.66%) |

The honest read: buy-and-hold captured more total upside over 5 years
because it never sells anything, but it also ate a brutal -76.6% drawdown
along the way and lost nearly half the account in the most recent year
alone. The trailing-stop strategy gave up some of that upside in exchange
for roughly half the drawdown in every window, and was the only one of
the two profitable in the choppy 2-year window. Neither is a guarantee -
this is one historical period, not a law of markets - but it's the
clearest tradeoff evidence gathered here.

Two configs were tried and rejected before landing back here:
- **`trailing_stop_pct: 0.02`** (tighter stop): cut drawdown further but
  got shaken out by routine BTC noise before trends developed, turning
  the 5-year result negative.
- **Fixed $20/trade, 0.2% take-profit, 5% stop-loss** (a scalping
  variant): came out essentially flat (+0.03-0.04% over every window
  tested) because the position size was too small for the target to be
  worth anything in dollars, and the 0.2% target was close to or smaller
  than the ~0.3% round-trip slippage this project models.

Don't treat this table as settled, either - it's one strategy family
(MA crossover + trailing stop) tuned on one asset's recent history.
Changing `trailing_stop_pct`, the MA windows, or the historical window
tested can all move these numbers a lot; re-run before trusting any
variant with real money.

## Tests

```bash
python -m pytest -v      # from this directory, or from the repo root
```

Covers the risk manager (daily loss halt, trailing stop triggering from
entry vs. from a new peak, fractional position sizing, cash-capping), the
crossover math (hand-computed small-window scenarios), and the backtest
engine end-to-end (fills, costs, the trailing stop forcing an exit, the
daily-loss halt blocking a same-day re-entry after a stopped-out position).
Nothing here hits the network.

## Next steps to build out

- [ ] Confirm Robinhood's actual crypto MCP tool names/schema and fix
      `execution.py::to_mcp_args`
- [ ] Try trailing stops between 2% and 10% (only the two extremes have
      been tested) to see if there's a better drawdown/return tradeoff
- [ ] Test across more/different historical windows, including a real
      bear market (2022) rather than just the last 1/2/5 years from today
- [ ] No news/sentiment layer yet (parent project has one for equities);
      decide if that's worth adding for crypto or intentionally out of scope
