"""Unit tests for GDELT signal with mocked API + LLM."""
import pytest
from unittest.mock import patch, MagicMock
from app.signals.gdelt import get_signal


def _mock_llm(score: float, confidence: float, summary: str = "Test summary"):
    import json
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "score": score,
        "confidence": confidence,
        "summary": summary,
    })
    return mock_client


class TestGetSignal:
    def test_positive_sentiment(self):
        headlines = ["Apple hits record high", "Strong iPhone demand", "AAPL beats estimates"]
        with patch("app.signals.gdelt._fetch_headlines", return_value=headlines), \
             patch("app.signals.gdelt.OpenAI", return_value=_mock_llm(0.8, 0.7)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL", "Apple")
        assert result["score"] == pytest.approx(0.8)
        assert result["confidence"] == pytest.approx(0.7)

    def test_negative_sentiment(self):
        headlines = ["Apple layoffs announced", "iPhone sales slump"]
        with patch("app.signals.gdelt._fetch_headlines", return_value=headlines), \
             patch("app.signals.gdelt.OpenAI", return_value=_mock_llm(-0.6, 0.5)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL")
        assert result["score"] == pytest.approx(-0.6)

    def test_no_headlines_returns_zero(self):
        with patch("app.signals.gdelt._fetch_headlines", return_value=[]), \
             patch("app.signals.gdelt.OpenAI", return_value=MagicMock()), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL")
        assert result["score"] == 0.0
        assert result["confidence"] == 0.0

    def test_score_clamped_to_range(self):
        with patch("app.signals.gdelt._fetch_headlines", return_value=["headline"]), \
             patch("app.signals.gdelt.OpenAI", return_value=_mock_llm(5.0, 2.0)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL")
        assert result["score"] <= 1.0
        assert result["confidence"] <= 1.0

    def test_api_error_returns_zero(self):
        with patch("app.signals.gdelt._fetch_headlines", side_effect=Exception("timeout")), \
             patch("app.signals.gdelt.OpenAI", return_value=MagicMock()), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL")
        assert result["score"] == 0.0
