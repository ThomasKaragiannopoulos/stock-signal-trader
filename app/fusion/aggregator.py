"""
Weighted fusion of up to four signal scores into a single confidence score + direction.
Confidence: sum of active signal confidences / penalty divisor.
  4 active → /4.0, 3 → /3.0, 2 → /2.5, 1 → /1.7
NN signal has confidence=0 until enough trades exist — excluded from fusion automatically.
"""

WEIGHTS = {
    "stocktwits": 0.30,
    "gdelt":       0.25,
    "technical":   0.25,
    "nn":          0.20,
}
_CONF_DIVISOR = {1: 1.7, 2: 2.5, 3: 3.0, 4: 4.0}


def fuse(
    stocktwits: dict,
    gdelt: dict,
    technical: dict,
    nn: dict | None = None,
) -> dict:
    """
    Args:
        Each dict has keys: score (float), confidence (float), detail (dict)
        nn is optional — omit or pass None when no model is trained yet.

    Returns:
        {
            "fused_score": float in [-1, +1],
            "fused_confidence": float in [0, 1],
            "direction": "bullish" | "bearish" | "neutral",
            "opportunity": bool (always True),
        }
    """
    signals: dict[str, dict] = {
        "stocktwits": stocktwits,
        "gdelt":      gdelt,
        "technical":  technical,
    }
    if nn is not None:
        signals["nn"] = nn

    # Weighted score (each signal weighted by confidence × source weight)
    total_weight = 0.0
    weighted_score = 0.0
    for name, sig in signals.items():
        w = WEIGHTS[name] * sig["confidence"]
        weighted_score += sig["score"] * w
        total_weight += w

    fused_score = (weighted_score / total_weight) if total_weight > 0 else 0.0

    # Confidence: sum active confidences / penalty divisor
    active = {n: s for n, s in signals.items() if s["confidence"] > 0}
    n_active = len(active)
    if n_active == 0:
        fused_confidence = 0.0
    else:
        total_conf = sum(s["confidence"] for s in active.values())
        fused_confidence = min(1.0, total_conf / _CONF_DIVISOR[n_active])

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
