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
strategy.py    - Two strategies:
                   MomentumStrategy: dual-MA-crossover, same idea as the
                     equity scaffold's, implemented fresh for a single
                     symbol. Fires at most once per bar; on daily bars,
                     effectively once per day.
                   SwingReversalStrategy: buy on a % pullback from the
                     recent local high, sell on a % bounce off the recent
                     local low - meant to run on intraday bars so it can
                     round-trip multiple times in a single day. This is
                     the current config.yaml default; see "Current
                     default" below for why and what it actually is/isn't.
risk.py        - RiskManager: trailing stop (exit on pullback from peak,
                 not a fixed target - lets a trend keep running) + a daily
                 loss halt. At most one position ever (single asset), so
                 there's no multi-symbol position-limit logic to carry.
backtest.py    - Bar-by-bar single-asset backtest engine, fractional qty.
                 Works on daily or intraday bars - granularity comes from
                 whatever price_data it's given.
data.py        - load_btc_history: daily BTC-USD bars via yfinance.
                 load_btc_intraday_history: hourly (or finer) bars, for
                 strategies that need same-day reactions - yfinance's free
                 history for these is much shorter-range than daily.
execution.py   - OrderIntent for Claude Code to review/submit via the
                 Robinhood MCP connector - see the warning below.
run_backtest.py - CLI entrypoint. Reads strategy.name from config.yaml to
                 pick MomentumStrategy vs. SwingReversalStrategy.
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
python run_backtest.py                # real BTC-USD hourly data, config.yaml's lookback_days
python run_backtest.py --days 90       # override the lookback window
```

## Current default: swing reversal on hourly bars, 24-bar/5% threshold, 6% trailing stop

This is the config in `config.yaml` today, and it's new - it replaced the
20/50 MA crossover (still available, see `strategy.py`'s `MomentumStrategy`
and switch `strategy.name` back to `momentum_ma_crossover` to use it).

**What "swing reversal" actually means here:** the ask behind this was
"sell at the day's high, buy at the day's low, multiple times a day." That
exact target can't be computed without hindsight - a strategy can't know a
day's high or low until the day is over, so trying to hit it exactly would
mean the backtest (or a live version) is cheating on future information.
`SwingReversalStrategy` is the closest tradeable approximation: it buys
once price has pulled back `reversal_pct` from the recent `lookback_bars`-bar
high, and sells once price has bounced `reversal_pct` off the recent low -
using only bars already seen. Run on hourly bars, it can and does fire
multiple times in a single day.

**The threshold size matters a lot more than expected, because of trading
costs.** A tight threshold (short lookback, small `reversal_pct`) trades
very often - hundreds of times a year - and this project's slippage model
(15bps per side, i.e. ~30bps round-trip) quietly eats the strategy alive
at that frequency. Backtested over the last year of real BTC-USD hourly
data:

| Config (lookback / reversal_pct / trailing stop) | Trades/yr | Return | Max drawdown |
|---|---|---|---|
| 12 / 1.5% / 4% | 527 | -47.51% | -54.72% |
| 12 / 3% / 4% | 196 | -33.85% | -43.02% |
| 24 / 3% / 4% | 250 | -18.57% | -37.94% |
| **24 / 5% / 6% (current default)** | **72** | **+3.06%** | **-22.33%** |
| 48 / 5% / 8% | 68 | -33.98% | -45.96% |

For context, buy-and-hold over that same (declining) year returned
-44.74%. The current default isn't a big winner in absolute terms, but it
held up far better than buy-and-hold across every window checked:

| Window | Buy & hold | This strategy |
|---|---|---|
| 90 days | -15.75% | -1.12% (dd -10.78%, 12 trades) |
| 180 days | -26.03% | +7.11% (dd -12.56%, 38 trades) |
| 365 days | -44.74% | +3.06% (dd -22.33%, 72 trades) |

Treat this as a smoke test, not a validated config the way the old
MA-crossover table was - it's one parameter family, checked against one
(bad, declining) year of BTC history, and the 48/5%/8% row shows results
don't move smoothly as you scale the numbers up, so don't assume nearby
configs behave similarly. Before trusting any variant with real money:
try more thresholds and lookback windows, check a rising/choppy period
too (not just a declining one), and consider whether the slippage model
(15bps/side) matches what you'd actually pay.

## Tests

```bash
python -m pytest -v      # from this directory, or from the repo root
```

Covers the risk manager (daily loss halt, trailing stop triggering from
entry vs. from a new peak, fractional position sizing, cash-capping), the
crossover math and swing-reversal math (hand-computed small-window
scenarios, including one that fires a buy then a sell within the same
calendar day), and the backtest engine end-to-end (fills, costs, the
trailing stop forcing an exit, the daily-loss halt blocking a same-day
re-entry after a stopped-out position). Nothing here hits the network.

## Next steps to build out

- [ ] Confirm Robinhood's actual crypto MCP tool names/schema and fix
      `execution.py::to_mcp_args`
- [ ] Sweep `lookback_bars`/`reversal_pct` more thoroughly than the five
      configs checked so far - results didn't move smoothly as those were
      scaled up, so there's likely a better combination nearby
- [ ] Test the swing-reversal strategy across a rising or choppy period,
      not just the declining year checked so far - a strategy that beats
      buy-and-hold in a crash isn't automatically good in a rally
- [ ] Test across a real bear market (2022) once/if a data source with
      longer intraday history than yfinance's ~729-day window is wired in
- [ ] No news/sentiment layer yet (parent project has one for equities);
      decide if that's worth adding for crypto or intentionally out of scope
