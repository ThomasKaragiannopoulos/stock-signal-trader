"""
GDELT signal: query GDELT Article Search API for recent news on a company,
use LLM (batched) to assign sentiment score in [-1, +1].
"""
import json
import os
from datetime import datetime, timedelta

import httpx
from openai import OpenAI

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


def fetch_articles(ticker: str, company_name: str | None = None) -> list[str]:
    """HTTP only — fetch GDELT headlines. Returns [] on error or rate limit."""
    end = datetime.utcnow()
    start = end - timedelta(hours=24)
    params = {
        "query": company_name or ticker,
        "mode": "ArtList",
        "maxrecords": 10,
        "format": "json",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
    }
    try:
        resp = httpx.get(GDELT_BASE, params=params, timeout=15)
        if resp.status_code == 429:
            return []
        resp.raise_for_status()
        articles = resp.json().get("articles", []) or []
        return [a.get("title", "") for a in articles if a.get("title")]
    except Exception:
        return []


def batch_score(ticker_articles: list[dict], client: OpenAI) -> list[dict]:
    """
    Single LLM call to score news sentiment for each ticker.

    Args:
        ticker_articles: list of {"ticker": str, "headlines": list[str]}
    Returns:
        list of signal dicts in same order
    """
    if not ticker_articles:
        return []

    sections = []
    for i, item in enumerate(ticker_articles):
        if not item["headlines"]:
            sections.append(f"{i}. {item['ticker']}: no headlines")
        else:
            headlines = "\n".join(f"  - {h}" for h in item["headlines"])
            sections.append(f"{i}. {item['ticker']}:\n{headlines}")

    prompt = (
        "For each company's news headlines, score the overall sentiment for the stock's near-term price direction.\n"
        "Respond with a JSON object: {\"results\": [...]} where each element is "
        "{\"score\": float (-1.0 to 1.0), \"confidence\": float (0.0 to 1.0), \"summary\": str (1 sentence)}.\n\n"
        + "\n\n".join(sections)
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max(200, 100 * len(ticker_articles)),
            temperature=0,
            response_format={"type": "json_object"},
        )
        results = json.loads(resp.choices[0].message.content).get("results", [])
    except Exception:
        results = []

    signals = []
    for i, item in enumerate(ticker_articles):
        if not item["headlines"] or i >= len(results):
            signals.append({
                "score": 0.0,
                "confidence": 0.0,
                "detail": {"headline_count": len(item["headlines"]), "summary": "no data"},
            })
            continue
        try:
            r = results[i]
            score = round(max(-1.0, min(1.0, float(r["score"]))), 4)
            confidence = round(max(0.0, min(1.0, float(r.get("confidence", 0.5)))), 4)
            summary = r.get("summary", "")
        except (KeyError, ValueError, TypeError):
            score, confidence, summary = 0.0, 0.0, ""
        signals.append({
            "score": score,
            "confidence": confidence,
            "detail": {"headline_count": len(item["headlines"]), "summary": summary},
        })

    return signals


def get_signal(ticker: str, company_name: str | None = None) -> dict:
    """Single-ticker interface — used by tests and /debug endpoint."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    headlines = fetch_articles(ticker, company_name)
    return batch_score([{"ticker": ticker, "headlines": headlines}], client)[0]
