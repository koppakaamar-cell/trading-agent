"""
Tests for news/news_provider.py's get_next_earnings_date - specifically
the stale-date guard added this session (yfinance's calendar data can
return an already-passed date for less-followed tickers, which would
otherwise be mislabeled as "next"). yf.Ticker is monkeypatched so these
tests never hit the network.
"""

import datetime as dt

import news.news_provider as news_provider_module
from news.news_provider import get_next_earnings_date


class FakeTicker:
    def __init__(self, calendar):
        self.calendar = calendar


def test_future_earnings_date_is_returned(monkeypatch):
    future = dt.date.today() + dt.timedelta(days=10)
    monkeypatch.setattr(news_provider_module.yf, "Ticker", lambda symbol: FakeTicker({"Earnings Date": [future]}))
    assert get_next_earnings_date("AAPL") == future


def test_stale_past_earnings_date_returns_none(monkeypatch):
    """Regression test: PATH showed a next_earnings_date in the past
    during real testing this session before this guard was added."""
    past = dt.date.today() - dt.timedelta(days=30)
    monkeypatch.setattr(news_provider_module.yf, "Ticker", lambda symbol: FakeTicker({"Earnings Date": [past]}))
    assert get_next_earnings_date("AAPL") is None


def test_todays_date_is_not_treated_as_stale(monkeypatch):
    today = dt.date.today()
    monkeypatch.setattr(news_provider_module.yf, "Ticker", lambda symbol: FakeTicker({"Earnings Date": [today]}))
    assert get_next_earnings_date("AAPL") == today


def test_missing_calendar_data_returns_none(monkeypatch):
    monkeypatch.setattr(news_provider_module.yf, "Ticker", lambda symbol: FakeTicker({}))
    assert get_next_earnings_date("AAPL") is None


def test_ticker_exception_returns_none(monkeypatch):
    def raise_error(symbol):
        raise RuntimeError("network error")

    monkeypatch.setattr(news_provider_module.yf, "Ticker", raise_error)
    assert get_next_earnings_date("AAPL") is None
