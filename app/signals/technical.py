"""
Technical signal: yfinance OHLCV → RSI(14), MACD, 20/50 MA crossover → score in [-1, +1].
"""
import yfinance as yf
import pandas as pd


def _compute_rsi(close: pd.Series, period: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).rolling(period).mean()
    loss = (-delta.clip(upper=0)).rolling(period).mean()
    # When loss == 0 (only gains), RS → ∞ → RSI → 100; use tiny epsilon to avoid /0
    rs = gain / loss.replace(0, 1e-9)
    rsi = 100 - (100 / (1 + rs))
    return float(rsi.iloc[-1])


def _compute_macd_signal(close: pd.Series) -> float:
    """
    Returns +0.5 on bullish cross, -0.5 on bearish cross, 0 otherwise.
    Uses standard 12/26/9 MACD.
    """
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    signal = macd.ewm(span=9, adjust=False).mean()
    hist = macd - signal

    if len(hist) < 2:
        return 0.0

    prev_hist = float(hist.iloc[-2])
    curr_hist = float(hist.iloc[-1])

    if prev_hist < 0 and curr_hist > 0:
        return 0.5   # bullish cross
    if prev_hist > 0 and curr_hist < 0:
        return -0.5  # bearish cross
    return 0.0


def _compute_ma_score(close: pd.Series) -> float:
    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])
    price = float(close.iloc[-1])

    if price > ma20 and price > ma50:
        return 0.5
    if price < ma20 and price < ma50:
        return -0.5
    return 0.0


def get_signal(ticker: str, **_) -> dict:
    """
    Returns:
        {
            "score": float in [-1, +1],
            "confidence": float in [0, 1],
            "detail": {
                "rsi": float,
                "macd_signal": float,
                "ma_score": float,
                "price": float,
                "ma20": float,
                "ma50": float,
            }
        }
    """
    try:
        df = yf.download(ticker, period="60d", interval="1d", progress=False, auto_adjust=True)
    except Exception:
        return {"score": 0.0, "confidence": 0.0, "detail": {"error": "download_failed"}}

    if df is None or len(df) < 50:
        return {"score": 0.0, "confidence": 0.0, "detail": {"error": "insufficient_data"}}

    close = df["Close"].squeeze()

    rsi = _compute_rsi(close)
    macd_s = _compute_macd_signal(close)
    ma_s = _compute_ma_score(close)

    # RSI score: linear mapping
    if rsi < 30:
        rsi_score = 1.0
    elif rsi > 70:
        rsi_score = -1.0
    else:
        # proportional: 50 → 0, 30 → +1, 70 → -1
        rsi_score = (50 - rsi) / 20.0

    avg_score = (rsi_score + macd_s + ma_s) / 3.0

    # Confidence: higher when signals agree
    signals = [rsi_score, macd_s, ma_s]
    same_sign = sum(1 for s in signals if (s > 0) == (avg_score > 0) and s != 0)
    confidence = 0.4 + (0.2 * same_sign)  # 0.4 baseline, up to 1.0

    ma20 = float(close.rolling(20).mean().iloc[-1])
    ma50 = float(close.rolling(50).mean().iloc[-1])

    return {
        "score": round(max(-1.0, min(1.0, avg_score)), 4),
        "confidence": round(min(1.0, confidence), 4),
        "detail": {
            "rsi": round(rsi, 2),
            "macd_signal": macd_s,
            "ma_score": ma_s,
            "price": round(float(close.iloc[-1]), 4),
            "ma20": round(ma20, 4),
            "ma50": round(ma50, 4),
        },
    }
