"""Unit tests for GDELT signal with mocked HTTP + LLM."""
import json
import pytest
from unittest.mock import patch, MagicMock
from app.signals.gdelt import get_signal
import app.signals.gdelt as gdelt_mod


def _mock_client(score: float, confidence: float, summary: str = "Test summary"):
    mock = MagicMock()
    mock.chat.completions.create.return_value.choices[0].message.content = json.dumps({
        "results": [{"score": score, "confidence": confidence, "summary": summary}]
    })
    return mock


class TestGetSignal:
    def setup_method(self):
        gdelt_mod._cache.clear()

    def test_positive_sentiment(self):
        with patch("app.signals.gdelt.fetch_articles", return_value=["Apple hits record high", "Strong iPhone demand"]), \
             patch("app.signals.gdelt.OpenAI", return_value=_mock_client(0.8, 0.7)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL", "Apple")
        assert result["score"] == pytest.approx(0.8)
        assert result["confidence"] == pytest.approx(0.7)

    def test_negative_sentiment(self):
        with patch("app.signals.gdelt.fetch_articles", return_value=["Apple layoffs announced"]), \
             patch("app.signals.gdelt.OpenAI", return_value=_mock_client(-0.6, 0.5)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL2")
        assert result["score"] == pytest.approx(-0.6)

    def test_no_headlines_returns_zero(self):
        with patch("app.signals.gdelt.fetch_articles", return_value=[]), \
             patch("app.signals.gdelt.OpenAI", return_value=MagicMock()), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL3")
        assert result["score"] == 0.0
        assert result["confidence"] == 0.0

    def test_score_clamped_to_range(self):
        with patch("app.signals.gdelt.fetch_articles", return_value=["headline"]), \
             patch("app.signals.gdelt.OpenAI", return_value=_mock_client(5.0, 2.0)), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("AAPL4")
        assert result["score"] <= 1.0
        assert result["confidence"] <= 1.0

    def test_http_error_returns_zero(self):
        with patch("app.signals.gdelt.httpx.get", side_effect=Exception("timeout")), \
             patch("app.signals.gdelt.OpenAI", return_value=MagicMock()), \
             patch.dict("os.environ", {"OPENAI_API_KEY": "test"}):
            result = get_signal("ERRX", "ErrorCorp")
        assert result["score"] == 0.0
