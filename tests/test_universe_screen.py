"""
Tests for universe/screen.py's select_watchlist - liquidity, volatility
band, earnings proximity, sentiment, and correlation-cap filtering.
yf.download and the news lookups are all monkeypatched so these tests
never hit the network or depend on live market data.
"""

import datetime as dt

import numpy as np
import pandas as pd
import pytest

import universe.screen as screen_module
from universe.screen import UniverseCriteria, select_watchlist

DEFAULT_CRITERIA = UniverseCriteria(
    max_symbols=10, min_price=5.0, min_avg_volume=1_000_000,
    min_annualized_volatility=0.15, max_annualized_volatility=0.80,
    min_days_to_earnings=3, min_sentiment_score=-0.2, max_correlation=0.7,
)


def make_close_series(daily_pct: float, periods: int = 60, start_price: float = 100.0) -> pd.Series:
    """Deterministic alternating +/- daily_pct returns -> a predictable
    annualized volatility of roughly daily_pct * sqrt(252)."""
    dates = pd.bdate_range(start="2024-01-02", periods=periods)
    prices = [start_price]
    for i in range(periods - 1):
        change = daily_pct if i % 2 == 0 else -daily_pct
        prices.append(prices[-1] * (1 + change))
    return pd.Series(prices, index=dates)


def make_random_close_series(seed: int, periods: int = 60, vol: float = 0.015, start_price: float = 100.0) -> pd.Series:
    """Independent random-walk series for correlation tests - different
    seeds should land near-zero pairwise correlation."""
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range(start="2024-01-02", periods=periods)
    returns = rng.normal(0, vol, size=periods)
    prices = start_price * np.exp(np.cumsum(returns))
    return pd.Series(prices, index=dates)


def make_candidate(price=50.0, avg_volume_3m=5_000_000, market_cap=1e10) -> dict:
    return {"price": price, "avg_volume_3m": avg_volume_3m, "market_cap": market_cap}


def make_fake_download(close_map: dict):
    def fake_download(symbols, period="4mo", progress=False, group_by="ticker"):
        if len(symbols) == 1:
            closes = close_map[symbols[0]]
            return pd.DataFrame(
                {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": 1_000_000},
                index=closes.index,
            )
        frames = {}
        for symbol in symbols:
            closes = close_map[symbol]
            frames[symbol] = pd.DataFrame(
                {"Open": closes, "High": closes, "Low": closes, "Close": closes, "Volume": 1_000_000},
                index=closes.index,
            )
        return pd.concat(frames, axis=1)
    return fake_download


def patch_common(monkeypatch, close_map, earnings=None, sentiment_map=None):
    earnings = earnings or {}
    sentiment_map = sentiment_map or {}
    monkeypatch.setattr(screen_module.yf, "download", make_fake_download(close_map))
    monkeypatch.setattr(screen_module, "get_next_earnings_date", lambda symbol: earnings.get(symbol))
    monkeypatch.setattr(screen_module, "get_headlines", lambda symbol, limit=5: [{"symbol": symbol}])
    monkeypatch.setattr(
        screen_module, "score_headlines",
        lambda headlines: sentiment_map.get(headlines[0]["symbol"], 0.3) if headlines else 0.3,
    )


class TestLiquidityFilter:
    def test_excludes_cheap_and_illiquid_candidates(self, monkeypatch):
        candidates = {
            "GOOD": make_candidate(price=50.0, avg_volume_3m=5_000_000),
            "CHEAP": make_candidate(price=1.0, avg_volume_3m=5_000_000),   # below min_price
            "THIN": make_candidate(price=50.0, avg_volume_3m=10_000),      # below min_avg_volume
        }
        patch_common(monkeypatch, close_map={"GOOD": make_close_series(0.015)})

        selected = select_watchlist(candidates, DEFAULT_CRITERIA)

        assert {c["symbol"] for c in selected} == {"GOOD"}

    def test_missing_price_or_volume_excluded(self, monkeypatch):
        candidates = {
            "GOOD": make_candidate(),
            "NODATA": {"price": None, "avg_volume_3m": None, "market_cap": None},
        }
        patch_common(monkeypatch, close_map={"GOOD": make_close_series(0.015)})

        selected = select_watchlist(candidates, DEFAULT_CRITERIA)

        assert {c["symbol"] for c in selected} == {"GOOD"}


class TestVolatilityBandFilter:
    def test_excludes_outside_band(self, monkeypatch):
        candidates = {
            "LOWVOL": make_candidate(),   # ~1.6% annualized - below 15% floor
            "GOODVOL": make_candidate(),  # ~24% annualized - in band
            "HIGHVOL": make_candidate(),  # ~127% annualized - above 80% ceiling
        }
        close_map = {
            "LOWVOL": make_close_series(0.001),
            "GOODVOL": make_close_series(0.015),
            "HIGHVOL": make_close_series(0.08),
        }
        patch_common(monkeypatch, close_map)

        selected = select_watchlist(candidates, DEFAULT_CRITERIA)

        assert {c["symbol"] for c in selected} == {"GOODVOL"}


class TestEarningsProximityFilter:
    def test_excludes_earnings_too_soon(self, monkeypatch):
        candidates = {"SOON": make_candidate(), "SAFE": make_candidate()}
        close_map = {"SOON": make_close_series(0.015), "SAFE": make_close_series(0.015)}
        earnings = {
            "SOON": dt.date.today() + dt.timedelta(days=1),    # inside min_days_to_earnings=3
            "SAFE": dt.date.today() + dt.timedelta(days=10),
        }
        patch_common(monkeypatch, close_map, earnings=earnings)

        selected = select_watchlist(candidates, DEFAULT_CRITERIA)

        assert {c["symbol"] for c in selected} == {"SAFE"}

    def test_no_earnings_date_is_not_excluded(self, monkeypatch):
        candidates = {"UNKNOWN": make_candidate()}
        patch_common(monkeypatch, {"UNKNOWN": make_close_series(0.015)}, earnings={})

        selected = select_watchlist(candidates, DEFAULT_CRITERIA)

        assert {c["symbol"] for c in selected} == {"UNKNOWN"}


class TestSentimentFilter:
    def test_excludes_below_threshold(self, monkeypatch):
        candidates = {"POSITIVE": make_candidate(), "NEGATIVE": make_candidate()}
        close_map = {"POSITIVE": make_close_series(0.015), "NEGATIVE": make_close_series(0.015)}
        sentiment_map = {"POSITIVE": 0.5, "NEGATIVE": -0.6}
        patch_common(monkeypatch, close_map, sentiment_map=sentiment_map)

        selected = select_watchlist(candidates, DEFAULT_CRITERIA)

        assert {c["symbol"] for c in selected} == {"POSITIVE"}


class TestCorrelationCap:
    def test_perfectly_correlated_candidates_deduplicated(self, monkeypatch):
        shared = make_close_series(0.015)
        candidates = {
            "A1": make_candidate(avg_volume_3m=8_000_000),  # higher liquidity -> ranked first
            "A2": make_candidate(avg_volume_3m=5_000_000),
        }
        patch_common(monkeypatch, close_map={"A1": shared, "A2": shared.copy()})

        criteria = UniverseCriteria(**{**DEFAULT_CRITERIA.__dict__, "max_correlation": 0.9})
        selected = select_watchlist(candidates, criteria)

        assert len(selected) == 1
        assert selected[0]["symbol"] == "A1"

    def test_uncorrelated_candidates_both_kept(self, monkeypatch):
        candidates = {"R1": make_candidate(), "R2": make_candidate()}
        close_map = {"R1": make_random_close_series(seed=1), "R2": make_random_close_series(seed=2)}
        patch_common(monkeypatch, close_map)

        criteria = UniverseCriteria(**{**DEFAULT_CRITERIA.__dict__, "max_correlation": 0.5})
        selected = select_watchlist(candidates, criteria)

        assert {c["symbol"] for c in selected} == {"R1", "R2"}


class TestMaxSymbolsCap:
    def test_caps_at_max_symbols(self, monkeypatch):
        symbols = ["S1", "S2", "S3", "S4", "S5"]
        candidates = {s: make_candidate() for s in symbols}
        close_map = {s: make_random_close_series(seed=i) for i, s in enumerate(symbols)}
        patch_common(monkeypatch, close_map)

        criteria = UniverseCriteria(**{**DEFAULT_CRITERIA.__dict__, "max_symbols": 2, "max_correlation": 0.9})
        selected = select_watchlist(candidates, criteria)

        assert len(selected) == 2


class TestEmptyInputs:
    def test_no_candidates_returns_empty(self, monkeypatch):
        assert select_watchlist({}, DEFAULT_CRITERIA) == []

    def test_all_candidates_filtered_out_returns_empty(self, monkeypatch):
        candidates = {"CHEAP": make_candidate(price=1.0)}
        selected = select_watchlist(candidates, DEFAULT_CRITERIA)
        assert selected == []


class TestSingleCandidateDownloadPath:
    def test_single_symbol_uses_flat_column_download_shape(self, monkeypatch):
        """yfinance returns a flat (non-MultiIndex) frame when only one
        symbol is requested - a different code path than the batch case."""
        candidates = {"ONE": make_candidate()}
        patch_common(monkeypatch, {"ONE": make_close_series(0.015)})

        selected = select_watchlist(candidates, DEFAULT_CRITERIA)

        assert [c["symbol"] for c in selected] == ["ONE"]
