"""Unit tests for signal fusion aggregator."""
import pytest
from app.fusion.aggregator import fuse, OPPORTUNITY_THRESHOLD


def _sig(score: float, confidence: float) -> dict:
    return {"score": score, "confidence": confidence, "detail": {}}


class TestFuse:
    def test_bullish_alignment_gives_high_confidence(self):
        result = fuse(
            polymarket=_sig(0.8, 0.9),
            gdelt=_sig(0.6, 0.7),
            technical=_sig(0.7, 0.8),
        )
        assert result["direction"] == "bullish"
        assert result["fused_score"] > 0
        # All agree → agreement bonus applied
        assert result["fused_confidence"] >= OPPORTUNITY_THRESHOLD

    def test_bearish_alignment(self):
        result = fuse(
            polymarket=_sig(-0.7, 0.8),
            gdelt=_sig(-0.5, 0.6),
            technical=_sig(-0.6, 0.7),
        )
        assert result["direction"] == "bearish"
        assert result["fused_score"] < 0

    def test_disagreeing_signals_lower_confidence(self):
        # Mixed signals: one bullish, one bearish, one neutral
        result_agree = fuse(
            polymarket=_sig(0.8, 0.9),
            gdelt=_sig(0.7, 0.9),
            technical=_sig(0.6, 0.9),
        )
        result_disagree = fuse(
            polymarket=_sig(0.8, 0.9),
            gdelt=_sig(-0.7, 0.9),
            technical=_sig(0.1, 0.9),
        )
        assert result_agree["fused_confidence"] > result_disagree["fused_confidence"]

    def test_agreement_bonus_applied(self):
        """All three aligned → +0.15 bonus on confidence."""
        without_bonus = fuse(
            polymarket=_sig(0.8, 0.5),
            gdelt=_sig(-0.7, 0.5),
            technical=_sig(0.1, 0.5),
        )
        with_bonus = fuse(
            polymarket=_sig(0.8, 0.5),
            gdelt=_sig(0.7, 0.5),
            technical=_sig(0.6, 0.5),
        )
        assert with_bonus["fused_confidence"] > without_bonus["fused_confidence"]

    def test_neutral_when_near_zero(self):
        result = fuse(
            polymarket=_sig(0.02, 0.5),
            gdelt=_sig(0.01, 0.5),
            technical=_sig(-0.02, 0.5),
        )
        assert result["direction"] == "neutral"

    def test_zero_confidence_signals_return_zero_score(self):
        result = fuse(
            polymarket=_sig(0.9, 0.0),
            gdelt=_sig(0.9, 0.0),
            technical=_sig(0.9, 0.0),
        )
        assert result["fused_score"] == 0.0

    def test_opportunity_flag_above_threshold(self):
        result = fuse(
            polymarket=_sig(0.9, 0.95),
            gdelt=_sig(0.8, 0.9),
            technical=_sig(0.7, 0.85),
        )
        assert result["opportunity"] is True

    def test_opportunity_flag_below_threshold(self):
        result = fuse(
            polymarket=_sig(0.1, 0.2),
            gdelt=_sig(0.1, 0.1),
            technical=_sig(0.0, 0.1),
        )
        assert result["opportunity"] is False
