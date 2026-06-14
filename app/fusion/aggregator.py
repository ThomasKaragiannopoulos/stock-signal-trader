"""
Weighted fusion of three signal scores into a single confidence score + direction.
Confidence: sum of active signal confidences / divisor (3→3.0, 2→2.5, 1→1.7).
Missing signals are penalised via the divisor, not by zeroing their weight.
"""

WEIGHTS = {
    "polymarket": 0.4,
    "gdelt": 0.3,
    "technical": 0.3,
}
_CONF_DIVISOR = {3: 3.0, 2: 2.5, 1: 1.7}


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

    # Confidence: sum active signal confidences / penalty divisor
    active = {n: s for n, s in signals.items() if s["confidence"] > 0}
    n_active = len(active)
    if n_active == 0:
        fused_confidence = 0.0
    else:
        total_conf = sum(s["confidence"] for s in active.values())
        divisor = _CONF_DIVISOR[n_active]
        fused_confidence = min(1.0, total_conf / divisor)

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
        "opportunity": True,
    }
