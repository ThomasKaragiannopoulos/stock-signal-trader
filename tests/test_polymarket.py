"""Unit tests for Polymarket signal with mocked API + LLM."""
import pytest
from unittest.mock import patch, MagicMock
from app.signals.polymarket import get_signal, _extract_probability


class TestExtractProbability:
    def test_valid_price(self):
        market = {"outcomePrices": ["0.75", "0.25"]}
        assert _extract_probability(market) == pytest.approx(0.75)

    def test_missing_prices(self):
        assert _extract_probability({}) is None

    def test_invalid_price(self):
        market = {"outcomePrices": ["not_a_number"]}
        assert _extract_probability(market) is None


class TestGetSignal:
    def _mock_llm_pick(self, idx: int):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value.choices[0].message.content = str(idx)
        return mock_client

    def test_bullish_signal(self):
        markets = [{"id": "1", "question": "Will AAPL beat earnings?", "outcomePrices": ["0.75", "0.25"]}]
        with patch("app.signals.polymarket._search_markets", return_value=markets), \
             patch("app.signals.polymarket.OpenAI", return_value=self._mock_llm_pick(0)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL", "Apple")
        assert result["score"] > 0
        assert result["confidence"] > 0

    def test_bearish_signal(self):
        markets = [{"id": "2", "question": "Will AAPL miss earnings?", "outcomePrices": ["0.25", "0.75"]}]
        with patch("app.signals.polymarket._search_markets", return_value=markets), \
             patch("app.signals.polymarket.OpenAI", return_value=self._mock_llm_pick(0)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL", "Apple")
        assert result["score"] < 0

    def test_neutral_signal(self):
        markets = [{"id": "3", "question": "Neutral market", "outcomePrices": ["0.50", "0.50"]}]
        with patch("app.signals.polymarket._search_markets", return_value=markets), \
             patch("app.signals.polymarket.OpenAI", return_value=self._mock_llm_pick(0)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL", "Apple")
        assert result["score"] == 0.0

    def test_no_markets_returns_zero(self):
        with patch("app.signals.polymarket._search_markets", return_value=[]), \
             patch("app.signals.polymarket.OpenAI", return_value=self._mock_llm_pick(-1)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL", "Apple")
        assert result["score"] == 0.0
        assert result["confidence"] == 0.0

    def test_api_error_returns_zero(self):
        with patch("app.signals.polymarket._search_markets", side_effect=Exception("timeout")), \
             patch("app.signals.polymarket.OpenAI", return_value=MagicMock()), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL")
        assert result["score"] == 0.0
