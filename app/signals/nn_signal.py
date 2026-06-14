"""
Neural network signal: sklearn MLP trained on closed trade outcomes.
Falls back to neutral (confidence=0) when fewer than MIN_TRADES closed trades exist.
"""
import logging
import pickle
from pathlib import Path

import numpy as np
from sklearn.neural_network import MLPClassifier
from sklearn.preprocessing import StandardScaler

logger = logging.getLogger(__name__)

MIN_TRADES = 10
MODEL_PATH = Path(__file__).parent.parent.parent / "nn_model.pkl"

_model: MLPClassifier | None = None
_scaler: StandardScaler | None = None
_trained_on: int = 0


def load_model() -> None:
    """Load persisted model on startup."""
    global _model, _scaler, _trained_on
    if MODEL_PATH.exists():
        try:
            with open(MODEL_PATH, "rb") as f:
                data = pickle.load(f)
            _model = data["model"]
            _scaler = data["scaler"]
            _trained_on = data.get("n_trades", 0)
            logger.info("NN: loaded model trained on %d trades", _trained_on)
        except Exception:
            logger.exception("NN: failed to load persisted model")


def maybe_retrain(session) -> None:
    """Retrain if new closed trades exist since last training."""
    global _model, _scaler, _trained_on

    from app.models import Opportunity, Trade

    rows = (
        session.query(Trade, Opportunity)
        .join(Opportunity, Trade.opportunity_id == Opportunity.id)
        .filter(Trade.status == "closed")
        .filter(Trade.realised_pnl.isnot(None))
        .all()
    )

    n = len(rows)
    if n < MIN_TRADES:
        logger.info("NN: %d closed trades, need %d — no model yet", n, MIN_TRADES)
        _trained_on = n
        return

    if n == _trained_on:
        logger.info("NN: no new trades since last training (%d)", n)
        return

    X = np.array([
        [opp.polymarket_score or 0.0, opp.gdelt_score or 0.0, opp.technical_score or 0.0]
        for trade, opp in rows
    ])
    y = np.array([1 if trade.realised_pnl > 0 else 0 for trade, opp in rows])

    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(X)

    model = MLPClassifier(hidden_layer_sizes=(16, 8), max_iter=500, random_state=42)
    model.fit(X_scaled, y)

    _model = model
    _scaler = scaler
    _trained_on = n

    with open(MODEL_PATH, "wb") as f:
        pickle.dump({"model": model, "scaler": scaler, "n_trades": n}, f)

    logger.info("NN: retrained on %d trades", n)


def get_signal(st_score: float, gdelt_score: float, tech_score: float) -> dict:
    """
    Returns a signal dict. score is rescaled profit probability:
      p_profit=1.0 → score=+1.0, p_profit=0.5 → score=0.0, p_profit=0.0 → score=-1.0
    confidence=0 when no model (doesn't count toward fusion).
    """
    if _model is None or _scaler is None:
        return {
            "score": 0.0,
            "confidence": 0.0,
            "detail": {"status": "no_model", "n_trades": _trained_on},
        }
    try:
        X = np.array([[st_score, gdelt_score, tech_score]])
        X_scaled = _scaler.transform(X)
        proba = _model.predict_proba(X_scaled)[0]
        p_profit = float(proba[1]) if len(proba) > 1 else 0.5
        score = round((p_profit - 0.5) * 2.0, 4)
        confidence = round(abs(p_profit - 0.5) * 2.0, 4)
        return {
            "score": max(-1.0, min(1.0, score)),
            "confidence": confidence,
            "detail": {"status": "active", "n_trades": _trained_on, "p_profit": round(p_profit, 4)},
        }
    except Exception:
        logger.exception("NN: prediction failed")
        return {"score": 0.0, "confidence": 0.0, "detail": {"status": "error", "n_trades": _trained_on}}
