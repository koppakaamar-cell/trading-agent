"""
Tests for universe/candidates.py - the screener pool fetch and dedup
logic. yf.screen is monkeypatched so these tests never hit the network.
"""

import universe.candidates as candidates_module
from universe.candidates import get_candidate_symbols


def make_quotes(rows):
    return {"quotes": [
        {"symbol": s, "regularMarketPrice": p, "averageDailyVolume3Month": v, "marketCap": mc}
        for s, p, v, mc in rows
    ]}


def test_dedupes_across_screeners(monkeypatch):
    responses = {
        "most_actives": make_quotes([("AAA", 10.0, 1_000_000, 1e9), ("BBB", 20.0, 2_000_000, 2e9)]),
        "day_gainers": make_quotes([("AAA", 10.5, 1_100_000, 1e9), ("CCC", 30.0, 3_000_000, 3e9)]),
    }
    monkeypatch.setattr(candidates_module.yf, "screen", lambda name, count=25: responses[name])

    result = get_candidate_symbols(screeners=["most_actives", "day_gainers"], count_per_screener=25)

    assert set(result.keys()) == {"AAA", "BBB", "CCC"}
    assert result["AAA"]["price"] == 10.5  # later screener's data for a duplicate wins


def test_failed_screener_is_skipped_not_fatal(monkeypatch):
    def flaky_screen(name, count=25):
        if name == "broken":
            raise RuntimeError("network error")
        return make_quotes([("OK", 10.0, 1_000_000, 1e9)])

    monkeypatch.setattr(candidates_module.yf, "screen", flaky_screen)

    result = get_candidate_symbols(screeners=["broken", "most_actives"], count_per_screener=25)

    assert set(result.keys()) == {"OK"}


def test_skips_quotes_without_symbol(monkeypatch):
    monkeypatch.setattr(
        candidates_module.yf, "screen",
        lambda name, count=25: {"quotes": [{"regularMarketPrice": 10.0}]},
    )

    result = get_candidate_symbols(screeners=["most_actives"], count_per_screener=25)

    assert result == {}
