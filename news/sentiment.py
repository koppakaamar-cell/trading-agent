"""
Lexicon-based sentiment scoring for headlines, via VADER (no API key, no
model download - just a bundled word/intensity lexicon tuned for short,
informal text like headlines and social posts).

This is informational only (see README / order_intent.py) - it does not
gate or resize any trade. It exists so a signal or order intent can carry
"here's what the news looked like when this fired" for a human or Claude
to weigh before submitting an order.
"""

from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer

_analyzer = SentimentIntensityAnalyzer()


def score_headline(text: str) -> float:
    """Returns VADER's compound score in [-1.0, 1.0]: negative = bearish
    tone, positive = bullish tone, ~0 = neutral/mixed."""
    if not text:
        return 0.0
    return _analyzer.polarity_scores(text)["compound"]


def score_headlines(headlines: list[dict]) -> float:
    """Averages the compound sentiment of a list of headline dicts (as
    returned by news_provider.get_headlines), scoring on title + summary.
    Returns 0.0 for an empty list."""
    if not headlines:
        return 0.0
    scores = [score_headline(f"{h.get('title', '')}. {h.get('summary', '')}") for h in headlines]
    return sum(scores) / len(scores)


def sentiment_label(score: float) -> str:
    if score >= 0.2:
        return "positive"
    if score <= -0.2:
        return "negative"
    return "neutral"
