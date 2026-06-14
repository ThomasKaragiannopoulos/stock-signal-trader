"""
Polymarket signal: query Gamma API for markets adjacent to a ticker,
use LLM to pick the most relevant market and extract implied probability,
then convert to a directional score in [-1, +1].
"""
import os
import httpx
from openai import OpenAI

GAMMA_BASE = "https://gamma-api.polymarket.com"
BULLISH_THRESHOLD = 0.60
BEARISH_THRESHOLD = 0.40


def _search_markets(query: str, limit: int = 5) -> list[dict]:
    url = f"{GAMMA_BASE}/markets"
    params = {"search": query, "active": "true", "limit": limit}
    resp = httpx.get(url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def _pick_market_with_llm(ticker: str, markets: list[dict], client: OpenAI) -> dict | None:
    if not markets:
        return None

    summaries = "\n".join(
        f"{i}. [{m.get('id')}] {m.get('question', '')} — outcomes: {m.get('outcomePrices', [])}"
        for i, m in enumerate(markets)
    )
    prompt = (
        f"Given the stock ticker {ticker}, which of the following Polymarket prediction markets "
        f"is most directly adjacent to the stock's price direction?\n\n"
        f"{summaries}\n\n"
        "Reply with the index number (0-based) of the best market, or -1 if none are relevant. "
        "Only reply with the integer."
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=5,
        temperature=0,
    )
    raw = response.choices[0].message.content.strip()
    try:
        idx = int(raw)
    except ValueError:
        return None
    if idx < 0 or idx >= len(markets):
        return None
    return markets[idx]


def _extract_probability(market: dict) -> float | None:
    """Extract implied probability for the first (typically YES) outcome."""
    prices = market.get("outcomePrices")
    if not prices:
        return None
    try:
        return float(prices[0])
    except (ValueError, IndexError, TypeError):
        return None


def get_signal(ticker: str, company_name: str | None = None) -> dict:
    """
    Returns:
        {
            "score": float in [-1, +1],
            "confidence": float in [0, 1],
            "detail": {
                "market_question": str | None,
                "implied_prob": float | None,
                "market_id": str | None,
            }
        }
    """
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    query = company_name or ticker
    try:
        markets = _search_markets(query)
    except Exception:
        return {"score": 0.0, "confidence": 0.0, "detail": {"error": "api_unavailable"}}

    market = _pick_market_with_llm(ticker, markets, client)
    if market is None:
        return {"score": 0.0, "confidence": 0.0, "detail": {"market_question": None, "implied_prob": None}}

    prob = _extract_probability(market)
    if prob is None:
        return {"score": 0.0, "confidence": 0.0, "detail": {"market_question": market.get("question"), "implied_prob": None}}

    if prob > BULLISH_THRESHOLD:
        score = min(1.0, (prob - BULLISH_THRESHOLD) / (1.0 - BULLISH_THRESHOLD))
    elif prob < BEARISH_THRESHOLD:
        score = -min(1.0, (BEARISH_THRESHOLD - prob) / BEARISH_THRESHOLD)
    else:
        score = 0.0

    confidence = abs(prob - 0.5) * 2  # 0 at prob=0.5, 1 at prob=0 or 1

    return {
        "score": round(score, 4),
        "confidence": round(confidence, 4),
        "detail": {
            "market_question": market.get("question"),
            "implied_prob": prob,
            "market_id": market.get("id"),
        },
    }
