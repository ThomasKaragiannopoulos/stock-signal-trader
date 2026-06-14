"""Unit tests for technical signal with mocked yfinance."""
import pandas as pd
import pytest
from unittest.mock import patch
from app.signals.technical import get_signal, _compute_rsi, _compute_macd_signal, _compute_ma_score


def _make_close(values: list[float]) -> pd.Series:
    return pd.Series(values, dtype=float)


class TestComputeRSI:
    def test_oversold_returns_near_positive(self):
        # Declining prices → RSI < 30 → score should be +1
        prices = [100 - i for i in range(60)]
        close = _make_close(prices)
        rsi = _compute_rsi(close)
        assert rsi < 30

    def test_overbought_returns_near_negative(self):
        # Monotonically rising prices → no losses → RSI ≈ 100 (only gains)
        prices = [100 + i for i in range(60)]
        close = _make_close(prices)
        rsi = _compute_rsi(close)
        assert rsi > 90


class TestMACDSignal:
    def test_bullish_crossover(self):
        # Flat then spike → should produce a bullish cross
        prices = [100.0] * 40 + [110.0 + i for i in range(20)]
        close = _make_close(prices)
        # Just check it returns a float in valid range
        result = _compute_macd_signal(close)
        assert result in (-0.5, 0.0, 0.5)

    def test_insufficient_data(self):
        close = _make_close([100.0])
        assert _compute_macd_signal(close) == 0.0


class TestMAScore:
    def test_price_above_both_ma(self):
        # Price well above MA20 and MA50
        prices = [100.0] * 50 + [200.0] * 10
        close = _make_close(prices)
        score = _compute_ma_score(close)
        assert score == 0.5

    def test_price_below_both_ma(self):
        prices = [200.0] * 50 + [50.0] * 10
        close = _make_close(prices)
        score = _compute_ma_score(close)
        assert score == -0.5


class TestGetSignal:
    def _make_df(self, close_prices):
        idx = pd.date_range("2024-01-01", periods=len(close_prices), freq="D")
        return pd.DataFrame({"Close": close_prices, "Open": close_prices, "High": close_prices, "Low": close_prices, "Volume": [1e6] * len(close_prices)}, index=idx)

    def test_returns_score_in_range(self):
        prices = [100.0 + i * 0.1 for i in range(60)]
        df = self._make_df(prices)
        with patch("yfinance.download", return_value=df):
            result = get_signal("AAPL")
        assert -1.0 <= result["score"] <= 1.0
        assert 0.0 <= result["confidence"] <= 1.0

    def test_download_error_returns_zero(self):
        with patch("yfinance.download", side_effect=Exception("network error")):
            result = get_signal("AAPL")
        assert result["score"] == 0.0
        assert result["confidence"] == 0.0

    def test_insufficient_data_returns_zero(self):
        df = self._make_df([100.0] * 10)
        with patch("yfinance.download", return_value=df):
            result = get_signal("AAPL")
        assert result["score"] == 0.0
