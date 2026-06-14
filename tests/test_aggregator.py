"""Unit tests for signal fusion aggregator."""
import pytest
from app.fusion.aggregator import fuse


def _sig(score: float, confidence: float) -> dict:
    return {"score": score, "confidence": confidence, "detail": {}}


class TestFuse:
    def test_bullish_alignment(self):
        result = fuse(stocktwits=_sig(0.8, 0.9), gdelt=_sig(0.6, 0.7), technical=_sig(0.7, 0.8))
        assert result["direction"] == "bullish"
        assert result["fused_score"] > 0

    def test_bearish_alignment(self):
        result = fuse(stocktwits=_sig(-0.7, 0.8), gdelt=_sig(-0.5, 0.6), technical=_sig(-0.6, 0.7))
        assert result["direction"] == "bearish"
        assert result["fused_score"] < 0

    def test_neutral_when_near_zero(self):
        result = fuse(stocktwits=_sig(0.02, 0.5), gdelt=_sig(0.01, 0.5), technical=_sig(-0.02, 0.5))
        assert result["direction"] == "neutral"

    def test_zero_confidence_gives_zero_score(self):
        result = fuse(stocktwits=_sig(0.9, 0.0), gdelt=_sig(0.9, 0.0), technical=_sig(0.9, 0.0))
        assert result["fused_score"] == 0.0

    def test_opportunity_always_true(self):
        result = fuse(stocktwits=_sig(0.1, 0.1), gdelt=_sig(0.1, 0.1), technical=_sig(0.0, 0.1))
        assert result["opportunity"] is True

    def test_confidence_three_active(self):
        # 3 signals each conf=0.9: total=2.7 / 3.0 = 0.9
        result = fuse(stocktwits=_sig(0.5, 0.9), gdelt=_sig(0.5, 0.9), technical=_sig(0.5, 0.9))
        assert abs(result["fused_confidence"] - 0.9) < 0.01

    def test_confidence_penalty_one_active(self):
        # 1 signal conf=0.9: 0.9/1.7 < 3 signals: 2.7/3.0
        three = fuse(stocktwits=_sig(0.5, 0.9), gdelt=_sig(0.5, 0.9), technical=_sig(0.5, 0.9))
        one = fuse(stocktwits=_sig(0.5, 0.9), gdelt=_sig(0.0, 0.0), technical=_sig(0.0, 0.0))
        assert three["fused_confidence"] > one["fused_confidence"]

    def test_nn_low_conf_dilutes_confidence(self):
        # 3 signals conf=0.9: 2.7/3.0 = 0.9
        # 4 signals with nn conf=0.3: 3.0/4.0 = 0.75 — nn dilutes when weaker
        high = fuse(stocktwits=_sig(0.5, 0.9), gdelt=_sig(0.5, 0.9), technical=_sig(0.5, 0.9))
        diluted = fuse(stocktwits=_sig(0.5, 0.9), gdelt=_sig(0.5, 0.9), technical=_sig(0.5, 0.9), nn=_sig(0.5, 0.3))
        assert high["fused_confidence"] > diluted["fused_confidence"]

    def test_nn_none_same_as_omitted(self):
        a = fuse(stocktwits=_sig(0.5, 0.6), gdelt=_sig(0.5, 0.6), technical=_sig(0.5, 0.6))
        b = fuse(stocktwits=_sig(0.5, 0.6), gdelt=_sig(0.5, 0.6), technical=_sig(0.5, 0.6), nn=None)
        assert a["fused_confidence"] == b["fused_confidence"]

    def test_values_in_range(self):
        result = fuse(stocktwits=_sig(1.0, 1.0), gdelt=_sig(1.0, 1.0), technical=_sig(1.0, 1.0))
        assert -1.0 <= result["fused_score"] <= 1.0
        assert 0.0 <= result["fused_confidence"] <= 1.0
