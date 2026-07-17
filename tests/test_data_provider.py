"""
Tests for data/data_provider.py's CSV loader and quote-history normalizer.
load_from_yfinance is intentionally not covered here since it requires
network access - see the module docstring.
"""

import pandas as pd
import pytest

from data.data_provider import load_from_csv, bars_from_quote_history


class TestLoadFromCsv:
    def test_loads_and_sorts_by_date(self, tmp_path):
        csv_path = tmp_path / "bars.csv"
        csv_path.write_text(
            "date,open,high,low,close,volume\n"
            "2024-01-02,101,102,100,101.5,1000\n"
            "2024-01-01,100,101,99,100.5,900\n"
        )

        df = load_from_csv(str(csv_path))

        assert list(df.index) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.loc[pd.Timestamp("2024-01-01"), "close"] == 100.5

    def test_extra_columns_are_dropped(self, tmp_path):
        csv_path = tmp_path / "bars.csv"
        csv_path.write_text(
            "date,open,high,low,close,volume,adj_close\n"
            "2024-01-01,100,101,99,100.5,900,100.4\n"
        )

        df = load_from_csv(str(csv_path))

        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_missing_required_column_raises(self, tmp_path):
        csv_path = tmp_path / "bars.csv"
        csv_path.write_text(
            "date,open,high,low,close\n"
            "2024-01-01,100,101,99,100.5\n"
        )

        with pytest.raises(ValueError, match="missing required columns"):
            load_from_csv(str(csv_path))

    def test_custom_date_column_name(self, tmp_path):
        csv_path = tmp_path / "bars.csv"
        csv_path.write_text(
            "timestamp,open,high,low,close,volume\n"
            "2024-01-01,100,101,99,100.5,900\n"
        )

        df = load_from_csv(str(csv_path), date_col="timestamp")

        assert df.index.name == "timestamp"
        assert df.loc[pd.Timestamp("2024-01-01"), "open"] == 100


class TestBarsFromQuoteHistory:
    def test_normalizes_and_sorts_quote_dicts(self):
        raw_quotes = [
            {"date": "2024-01-02", "open": 101, "high": 102, "low": 100, "close": 101.5, "volume": 1000},
            {"date": "2024-01-01", "open": 100, "high": 101, "low": 99, "close": 100.5, "volume": 900},
        ]

        df = bars_from_quote_history(raw_quotes)

        assert list(df.index) == [pd.Timestamp("2024-01-01"), pd.Timestamp("2024-01-02")]
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]
        assert df.loc[pd.Timestamp("2024-01-01"), "close"] == 100.5
