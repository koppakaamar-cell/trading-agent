"""
Tests for execution/order_intent.py's attach_news_context - specifically
the veto sequencing (macro checked before per-symbol, neither ever touches
SELLs). news.context.build_context is monkeypatched so these tests never
hit the network or depend on live market data.
"""

from execution.order_intent import OrderIntent, attach_news_context
from news.filter import MacroFilterConfig, NewsFilterConfig


def patch_build_context(monkeypatch, sentiment_score=0.0, sentiment_label="neutral"):
    fake_context = {
        "headlines": [],
        "sentiment_score": sentiment_score,
        "sentiment_label": sentiment_label,
        "next_earnings_date": None,
        "fundamentals": {},
    }
    monkeypatch.setattr("news.context.build_context", lambda symbol, headline_limit=5: dict(fake_context))


class TestAttachNewsContext:
    def test_sell_is_never_vetoed_even_with_hostile_config(self, monkeypatch):
        patch_build_context(monkeypatch, sentiment_score=-0.9, sentiment_label="negative")
        intent = OrderIntent(symbol="AAPL", side="sell", quantity=1, reason="stop-loss/take-profit")

        symbol_cfg = NewsFilterConfig(enabled=True, veto_sentiment_threshold=0.9)  # everything fails this
        macro_cfg = MacroFilterConfig(enabled=True, veto_sentiment_threshold=0.9)
        market_context = {"sentiment_score": -0.9, "sentiment_label": "negative"}

        attach_news_context(intent, filter_config=symbol_cfg, market_context=market_context,
                             macro_filter_config=macro_cfg)

        assert intent.context["veto"] == {"vetoed": False, "reason": None}

    def test_buy_vetoed_by_symbol_sentiment(self, monkeypatch):
        patch_build_context(monkeypatch, sentiment_score=-0.5, sentiment_label="negative")
        intent = OrderIntent(symbol="AAPL", side="buy", quantity=1, reason="test")

        symbol_cfg = NewsFilterConfig(enabled=True, veto_sentiment_threshold=-0.2)
        attach_news_context(intent, filter_config=symbol_cfg)

        assert intent.context["veto"]["vetoed"] is True
        assert "sentiment" in intent.context["veto"]["reason"]

    def test_buy_vetoed_by_macro_even_with_good_symbol_sentiment(self, monkeypatch):
        """Macro is checked first and should block the trade even when the
        symbol's own news would otherwise pass."""
        patch_build_context(monkeypatch, sentiment_score=0.8, sentiment_label="positive")
        intent = OrderIntent(symbol="AAPL", side="buy", quantity=1, reason="test")

        symbol_cfg = NewsFilterConfig(enabled=True, veto_sentiment_threshold=-0.2)  # would pass
        macro_cfg = MacroFilterConfig(enabled=True, veto_sentiment_threshold=-0.3)
        market_context = {"sentiment_score": -0.6, "sentiment_label": "negative"}  # risk-off

        attach_news_context(intent, filter_config=symbol_cfg, market_context=market_context,
                             macro_filter_config=macro_cfg)

        assert intent.context["veto"]["vetoed"] is True
        assert "macro" in intent.context["veto"]["reason"]

    def test_buy_passes_when_both_gates_clear(self, monkeypatch):
        patch_build_context(monkeypatch, sentiment_score=0.4, sentiment_label="positive")
        intent = OrderIntent(symbol="AAPL", side="buy", quantity=1, reason="test")

        symbol_cfg = NewsFilterConfig(enabled=True, veto_sentiment_threshold=-0.2)
        macro_cfg = MacroFilterConfig(enabled=True, veto_sentiment_threshold=-0.3)
        market_context = {"sentiment_score": 0.1, "sentiment_label": "neutral"}

        attach_news_context(intent, filter_config=symbol_cfg, market_context=market_context,
                             macro_filter_config=macro_cfg)

        assert intent.context["veto"] == {"vetoed": False, "reason": None}

    def test_disabled_gates_never_veto_regardless_of_sentiment(self, monkeypatch):
        patch_build_context(monkeypatch, sentiment_score=-0.9, sentiment_label="negative")
        intent = OrderIntent(symbol="AAPL", side="buy", quantity=1, reason="test")

        attach_news_context(intent)  # default configs are disabled

        assert intent.context["veto"] == {"vetoed": False, "reason": None}

    def test_market_context_attached_even_when_not_vetoing(self, monkeypatch):
        patch_build_context(monkeypatch)
        intent = OrderIntent(symbol="AAPL", side="buy", quantity=1, reason="test")
        market_context = {"sentiment_score": 0.1, "sentiment_label": "neutral", "headlines": []}

        attach_news_context(intent, market_context=market_context)

        assert intent.context["market"] == market_context

    def test_no_market_context_defaults_to_empty_dict(self, monkeypatch):
        patch_build_context(monkeypatch)
        intent = OrderIntent(symbol="AAPL", side="buy", quantity=1, reason="test")

        attach_news_context(intent)

        assert intent.context["market"] == {}
