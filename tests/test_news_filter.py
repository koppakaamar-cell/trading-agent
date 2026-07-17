"""
Tests for news/filter.py - the two sentiment veto gates (per-symbol and
macro/portfolio-wide). Pure logic against constructed context dicts, no
network calls.
"""

from news.filter import MacroFilterConfig, NewsFilterConfig, TradeVetoed, check_buy_veto, check_macro_veto


class TestCheckBuyVeto:
    def test_disabled_never_vetoes(self):
        config = NewsFilterConfig(enabled=False, veto_sentiment_threshold=-0.2)
        check_buy_veto({"sentiment_score": -0.9, "sentiment_label": "negative"}, config)  # no raise

    def test_negative_sentiment_below_threshold_vetoes(self):
        config = NewsFilterConfig(enabled=True, veto_sentiment_threshold=-0.2)
        try:
            check_buy_veto({"sentiment_score": -0.5, "sentiment_label": "negative"}, config)
            assert False, "expected TradeVetoed"
        except TradeVetoed as e:
            assert "sentiment" in e.reason

    def test_sentiment_at_threshold_vetoes(self):
        config = NewsFilterConfig(enabled=True, veto_sentiment_threshold=-0.2)
        try:
            check_buy_veto({"sentiment_score": -0.2, "sentiment_label": "negative"}, config)
            assert False, "expected TradeVetoed"
        except TradeVetoed:
            pass

    def test_positive_sentiment_above_threshold_does_not_veto(self):
        config = NewsFilterConfig(enabled=True, veto_sentiment_threshold=-0.2)
        check_buy_veto({"sentiment_score": 0.5, "sentiment_label": "positive"}, config)  # no raise

    def test_missing_sentiment_score_defaults_to_neutral(self):
        config = NewsFilterConfig(enabled=True, veto_sentiment_threshold=-0.2)
        check_buy_veto({}, config)  # defaults to 0.0, above threshold -> no raise


class TestCheckMacroVeto:
    def test_disabled_never_vetoes(self):
        config = MacroFilterConfig(enabled=False, veto_sentiment_threshold=-0.3)
        check_macro_veto({"sentiment_score": -0.9}, config)  # no raise

    def test_empty_market_context_never_vetoes(self):
        config = MacroFilterConfig(enabled=True, veto_sentiment_threshold=-0.3)
        check_macro_veto({}, config)  # no market data fetched -> can't veto on nothing
        check_macro_veto(None, config)

    def test_risk_off_sentiment_vetoes(self):
        config = MacroFilterConfig(enabled=True, veto_sentiment_threshold=-0.3)
        try:
            check_macro_veto({"sentiment_score": -0.6, "sentiment_label": "negative"}, config)
            assert False, "expected TradeVetoed"
        except TradeVetoed as e:
            assert "macro" in e.reason

    def test_neutral_sentiment_does_not_veto(self):
        config = MacroFilterConfig(enabled=True, veto_sentiment_threshold=-0.3)
        check_macro_veto({"sentiment_score": 0.01, "sentiment_label": "neutral"}, config)  # no raise
