"""
Polymarket signal: query Gamma API for markets adjacent to a ticker,
use LLM (batched) to pick the most relevant market and extract implied probability,
then convert to a directional score in [-1, +1].
"""
import json
import os

import httpx
from openai import OpenAI

GAMMA_BASE = "https://gamma-api.polymarket.com"
BULLISH_THRESHOLD = 0.60
BEARISH_THRESHOLD = 0.40

_NEUTRAL = {"score": 0.0, "confidence": 0.0, "detail": {"market_question": None, "implied_prob": None}}


def fetch_markets(ticker: str, company_name: str | None = None) -> list[dict]:
    """HTTP only — fetch Gamma API markets. Returns [] on error."""
    try:
        url = f"{GAMMA_BASE}/markets"
        params = {"search": company_name or ticker, "active": "true", "limit": 5}
        resp = httpx.get(url, params=params, timeout=10)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def _score_market(market: dict) -> dict:
    prices = market.get("outcomePrices")
    if not prices:
        return _NEUTRAL.copy()
    try:
        prob = float(prices[0])
    except (ValueError, IndexError, TypeError):
        return _NEUTRAL.copy()

    if prob > BULLISH_THRESHOLD:
        score = min(1.0, (prob - BULLISH_THRESHOLD) / (1.0 - BULLISH_THRESHOLD))
    elif prob < BEARISH_THRESHOLD:
        score = -min(1.0, (BEARISH_THRESHOLD - prob) / BEARISH_THRESHOLD)
    else:
        score = 0.0

    return {
        "score": round(score, 4),
        "confidence": round(abs(prob - 0.5) * 2, 4),
        "detail": {
            "market_question": market.get("question"),
            "implied_prob": prob,
            "market_id": market.get("id"),
        },
    }


def batch_score(ticker_markets: list[dict], client: OpenAI) -> list[dict]:
    """
    Single LLM call to pick the best Polymarket market for each ticker.

    Args:
        ticker_markets: list of {"ticker": str, "markets": list[dict]}
    Returns:
        list of signal dicts in same order
    """
    if not ticker_markets:
        return []

    lines = []
    for i, item in enumerate(ticker_markets):
        if not item["markets"]:
            lines.append(f"{i}. {item['ticker']}: no markets")
        else:
            summaries = "; ".join(
                f"[{j}] {m.get('question', '')} prices={m.get('outcomePrices', [])}"
                for j, m in enumerate(item["markets"])
            )
            lines.append(f"{i}. {item['ticker']}: {summaries}")

    prompt = (
        "For each stock ticker, pick the Polymarket prediction market most directly adjacent "
        "to the stock's price direction. Return {\"picks\": [...]} where each element is the "
        "0-based market index, or -1 if none are relevant.\n\n"
        + "\n".join(lines)
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0,
            response_format={"type": "json_object"},
        )
        picks = json.loads(resp.choices[0].message.content).get("picks", [])
    except Exception:
        picks = []

    results = []
    for i, item in enumerate(ticker_markets):
        try:
            idx = int(picks[i]) if i < len(picks) else -1
        except (ValueError, TypeError):
            idx = -1
        markets = item["markets"]
        results.append(_score_market(markets[idx]) if 0 <= idx < len(markets) else _NEUTRAL.copy())

    return results


def get_signal(ticker: str, company_name: str | None = None) -> dict:
    """Single-ticker interface — used by tests and /debug endpoint."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    markets = fetch_markets(ticker, company_name)
    return batch_score([{"ticker": ticker, "markets": markets}], client)[0]
