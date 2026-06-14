"""
Weighted fusion of three signal scores into a single confidence score + direction.
Weights: Polymarket 0.4, GDELT 0.3, Technical 0.3
Agreement bonus: +0.15 if all three signals align in direction.
"""

WEIGHTS = {
    "polymarket": 0.4,
    "gdelt": 0.3,
    "technical": 0.3,
}
AGREEMENT_BONUS = 0.15
OPPORTUNITY_THRESHOLD = 0.50


def fuse(
    polymarket: dict,
    gdelt: dict,
    technical: dict,
) -> dict:
    """
    Args:
        Each dict has keys: score (float), confidence (float), detail (dict)

    Returns:
        {
            "fused_score": float in [-1, +1],
            "fused_confidence": float in [0, 1],
            "direction": "bullish" | "bearish" | "neutral",
            "opportunity": bool,
        }
    """
    signals = {
        "polymarket": polymarket,
        "gdelt": gdelt,
        "technical": technical,
    }

    # Weighted score (each score weighted by its own confidence × source weight)
    total_weight = 0.0
    weighted_score = 0.0
    for name, sig in signals.items():
        w = WEIGHTS[name] * sig["confidence"]
        weighted_score += sig["score"] * w
        total_weight += w

    fused_score = (weighted_score / total_weight) if total_weight > 0 else 0.0

    # Base confidence: weighted average of individual confidences
    base_confidence = sum(
        sig["confidence"] * WEIGHTS[name] for name, sig in signals.items()
    )

    # Agreement bonus
    signs = [
        1 if sig["score"] > 0.05 else (-1 if sig["score"] < -0.05 else 0)
        for sig in signals.values()
    ]
    non_neutral = [s for s in signs if s != 0]
    all_agree = len(non_neutral) == 3 and len(set(non_neutral)) == 1

    fused_confidence = min(1.0, base_confidence + (AGREEMENT_BONUS if all_agree else 0.0))

    if fused_score > 0.05:
        direction = "bullish"
    elif fused_score < -0.05:
        direction = "bearish"
    else:
        direction = "neutral"

    return {
        "fused_score": round(fused_score, 4),
        "fused_confidence": round(fused_confidence, 4),
        "direction": direction,
        "opportunity": fused_confidence >= OPPORTUNITY_THRESHOLD,
    }
