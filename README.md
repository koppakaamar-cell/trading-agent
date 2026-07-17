# Trading Agent Scaffold

A modular framework for building, backtesting, and (eventually, carefully)
running a trading strategy against Robinhood via its official Agentic
Trading MCP server, from inside a Claude Code project.

**This is not a ready-to-fund trading bot.** It's a scaffold with a
starter momentum strategy so you have something concrete to backtest,
inspect, and improve. Nothing here is financial advice, and no strategy
here has been validated to make money.

## Architecture

```
strategies/    - Pure signal generation (Action: BUY/SELL/HOLD). No orders,
                 no position sizing. Swap strategies without touching
                 anything else. See strategies/base.py for the interface,
                 strategies/momentum.py for the starter implementation.

risk/          - Position sizing and hard safety limits: max position size,
                 daily loss halt, stop-losses, max open positions. This
                 layer can REJECT a trade the strategy wants to make.

data/          - Turns historical bars (CSV, yfinance, or eventually
                 Robinhood MCP quote history) into a consistent OHLCV
                 DataFrame shape that strategies consume.

universe/      - Screens a live, non-hardcoded pool of liquid/active stocks
                 (via Yahoo Finance screeners) into a watchlist, on
                 liquidity, volatility band, earnings proximity, sentiment,
                 and correlation. LIVE/PAPER ONLY - see build_watchlist.py.

news/          - Headlines, sentiment scoring, fundamentals, and next
                 earnings date, all free via yfinance (no API key). Current-
                 state only - can't be used inside the historical backtest
                 loop. Attached to OrderIntents as context, and can
                 optionally VETO a BUY intent if enabled. See news/filter.py.

backtest/      - Simulates strategy + risk manager bar-by-bar against
                 historical data. Read the docstring in engine.py for the
                 simplifications it makes (fills at same-bar close,
                 slippage/commission opt-in via config.yaml, etc).

execution/     - Does NOT call Robinhood directly. Converts a risk-approved
                 trade decision into an OrderIntent that Claude Code (with
                 the Robinhood MCP connector attached) reviews and submits.
                 attach_news_context() is where the news veto (if enabled)
                 gets checked, alongside the informational news snapshot.
```

## Why execution isn't in Python

The Robinhood MCP server's tools (`get_portfolio`, `review_equity_order`,
`place_equity_order`, etc.) are meant to be called by an AI agent with the
connector attached (Claude Code, Claude Desktop, etc.) - not by an
arbitrary script with an API key. That's a deliberate safety boundary on
Robinhood's side: a human/Claude checkpoint sits between "the strategy
wants to trade" and "an order hits the market." This scaffold keeps that
boundary intact rather than working around it.

The intended live loop, once you're ready:

1. Open this project in Claude Code with the Robinhood MCP connector
   configured (`https://agent.robinhood.com/mcp/trading`).
2. Ask Claude to pull current quotes for your watchlist via the MCP tools,
   feed them through `data_provider.bars_from_quote_history`, run the
   strategy + risk manager, and produce `OrderIntent`s.
3. Call `attach_news_context()` on each intent. If `news.enabled` is set in
   `config.yaml`, this also runs the sentiment veto on BUY intents - check
   `intent.context["veto"]["vetoed"]` and stop there if true.
4. Claude calls `review_equity_order` for each remaining intent and shows
   you the preview.
5. You (or Claude, if you've explicitly set up autonomous rules you're
   comfortable with) call `place_equity_order` only after review.

Trading is restricted to Robinhood's dedicated Agentic account - fund it
separately with an amount you're fully prepared to lose, not your main
brokerage balance.

## Getting started

```bash
pip install -r requirements.txt --break-system-packages
python run_backtest.py                # real data, last 2 years
python run_backtest.py --years 5       # real data, last 5 years (covers 2022)
python run_backtest.py --synthetic     # synthetic random-walk smoke test, offline
python run_backtest.py --no-news       # skip news/sentiment/fundamentals fetch
python build_watchlist.py              # screen today's candidates for live/paper trading
```

By default `run_backtest.py` pulls real historical data via yfinance for
your fixed `watchlist` symbols and runs the momentum strategy against it,
then prints a handful of sample `OrderIntent`s (with attached news
context) for the most recent trades, as a preview of what the live loop
would produce.

## Building a watchlist (not just 4 hardcoded symbols)

`config.yaml`'s `watchlist:` is a small, fixed, manually-picked list -
that's intentional for backtesting (see the warning below), but it's not
how you'd want to pick symbols to actually trade live. `build_watchlist.py`
screens a live pool instead:

1. Pulls a live, non-hardcoded candidate pool from Yahoo Finance's
   predefined screeners (`most_actives`, `day_gainers`,
   `growth_technology_stocks` by default - see `universe/candidates.py`
   for the full list of available screeners).
2. Filters on liquidity (`min_price`, `min_avg_volume`) and an annualized
   volatility band (`min_/max_annualized_volatility` - wide enough to have
   real moves, not so wide it's unhinged).
3. Excludes anything with earnings sooner than `min_days_to_earnings` away
   (avoids gap risk right as a position might open) and anything below
   `min_sentiment_score` on current headline sentiment.
4. Ranks the survivors and greedily selects up to `max_symbols`, skipping
   any candidate whose price-return correlation with an already-selected
   pick exceeds `max_correlation` - so you don't end up with, say, five
   different large-cap tech names that all move together.

All thresholds live under `universe:` in `config.yaml`.

**Lookahead/survivorship bias warning:** `build_watchlist.py`'s output
reflects *today's* liquidity, volatility, sentiment, and earnings
calendar. Never copy it into `watchlist:` and then backtest against it -
that would test the strategy on a universe selected using information
that didn't exist at the historical dates you're testing, which flatters
the backtest in a way that won't hold up live. Use `build_watchlist.py`
for the live/paper flow only; `run_backtest.py` intentionally keeps its
own fixed, manually-chosen watchlist.

## News, sentiment, and fundamentals

`news/` pulls current (not historical) headlines, VADER-scored sentiment,
next earnings date, and basic fundamentals for a symbol - all via
yfinance, no API key needed. This is attached to `OrderIntent.context` so
whoever (or whatever) reviews a trade before submitting it has "why"
alongside the price signal.

It's informational by default. Set `news.enabled: true` in `config.yaml`
to additionally let strongly negative sentiment veto a new BUY intent
(`news.veto_sentiment_threshold`, default `-0.2`). This never blocks SELL
intents, including stop-loss/take-profit exits - an exit that protects
capital should never be second-guessed by a headline. It's a second,
independent gate alongside the risk manager, not a replacement for it.

Because free news/fundamentals data is current-state only, none of this
can run inside the historical backtest loop - it only attaches to intents
built from the current bar (see `news/context.py` for why).

## Global/macro news

`news/market_news.py` pulls broad market news - not tied to any one
symbol - from major index tickers (`^GSPC`, `^DJI`, `^IXIC`, `^VIX`),
which in practice surfaces Fed/rates decisions and general risk-on/risk-off
tone. It's fetched once per run (not once per symbol) and attached to
every intent's `context["market"]`.

Set `news.macro.enabled: true` to let a strongly negative market-wide
reading veto ALL new BUYs, across every symbol, regardless of that
symbol's own sentiment - a portfolio-wide risk-off circuit breaker. It's
checked *before* the per-symbol veto (`intent.context["veto"]["reason"]`
will say "macro sentiment..." vs "sentiment..." depending on which gate
fired). Same rule as the per-symbol veto: never blocks SELLs.

## Tests

```bash
pip install -r requirements-dev.txt --break-system-packages
python -m pytest -v
```

Covers the risk manager (sizing, stop-loss/take-profit, and the daily-loss
halt's realized-vs-unrealized distinction), the backtest engine end-to-end
(scripted deterministic strategies, no network - includes an integration
test that reproduces the exact scenario the mark-to-market fix closed),
both news veto gates (per-symbol and macro, including gate ordering and
that SELLs are never touched), and `universe/`'s filtering stages
(liquidity, volatility band, earnings proximity, sentiment, correlation
cap). Everything that touches yfinance is monkeypatched, so the suite
never hits the network and never depends on live market conditions.

There's no coverage yet for `strategies/momentum.py`'s crossover math,
`data/data_provider.py`'s CSV/yfinance loaders, or `build_watchlist.py`/
`run_backtest.py` as scripts (only the modules they call) - worth adding
if you touch those next.

## Before you connect this to real money, honestly ask yourself

- Has the strategy been backtested across more than one market regime
  (a trending period AND a choppy/sideways period AND a downturn)? Try
  `--years 5` to include 2022.
- Have you set realistic `costs.slippage_bps` / `costs.commission_per_trade`
  in `config.yaml`, and accounted for taxes on short-term gains?
- Does the risk manager's daily loss halt and stop-loss actually match
  what you can emotionally and financially tolerate?
- If you've enabled the news veto, is `veto_sentiment_threshold` tuned
  against real headlines rather than just a guess?
- Have you run it in "paper"/preview mode (review_equity_order without
  place_equity_order) for long enough to trust the plumbing?
- Are you starting with an amount you are fully prepared to lose?

## Next steps to build out

- [ ] Add a second strategy (mean reversion) implementing `strategies/base.Strategy`
      to compare against momentum
- [ ] Add a `tests/` suite for the risk manager's edge cases (this is the
      code you most want to trust)
- [ ] Backtest the news veto's effect once you have a way to replay
      historical sentiment (free sources are current-only - see `news/`)
- [ ] Same caveat applies to `universe/` - if you want to know whether
      dynamic screening actually beats a fixed watchlist, you'd need point-
      in-time historical liquidity/volatility/sentiment data, not today's
- [ ] Confirm the exact Robinhood MCP tool schemas in Claude Code and
      update `execution/order_intent.py`'s `to_mcp_args` accordingly
