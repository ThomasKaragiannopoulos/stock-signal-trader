"""
GDELT signal: query GDELT Article Search API for recent news on a company,
use LLM to assign sentiment score in [-1, +1].
"""
import os
from datetime import datetime, timedelta
import httpx
from openai import OpenAI

GDELT_BASE = "https://api.gdeltproject.org/api/v2/doc/doc"


def _fetch_headlines(company: str, hours: int = 24) -> list[str]:
    end = datetime.utcnow()
    start = end - timedelta(hours=hours)
    params = {
        "query": company,
        "mode": "ArtList",
        "maxrecords": 10,
        "format": "json",
        "startdatetime": start.strftime("%Y%m%d%H%M%S"),
        "enddatetime": end.strftime("%Y%m%d%H%M%S"),
    }
    resp = httpx.get(GDELT_BASE, params=params, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    articles = data.get("articles", [])
    return [a.get("title", "") for a in articles if a.get("title")]


def _score_headlines_with_llm(ticker: str, headlines: list[str], client: OpenAI) -> dict:
    if not headlines:
        return {"score": 0.0, "confidence": 0.0, "summary": "No recent news found."}

    numbered = "\n".join(f"{i+1}. {h}" for i, h in enumerate(headlines))
    prompt = (
        f"Analyze the following recent news headlines about {ticker} from the last 24 hours.\n\n"
        f"{numbered}\n\n"
        "Return a JSON object with:\n"
        "- score: float from -1.0 (very bearish) to +1.0 (very bullish)\n"
        "- confidence: float from 0.0 to 1.0 (how certain you are given the news volume/clarity)\n"
        "- summary: one sentence explaining your score\n\n"
        "Respond ONLY with valid JSON, no markdown."
    )
    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=200,
        temperature=0,
        response_format={"type": "json_object"},
    )
    import json
    data = json.loads(response.choices[0].message.content)
    return {
        "score": float(data.get("score", 0.0)),
        "confidence": float(data.get("confidence", 0.0)),
        "summary": data.get("summary", ""),
    }


def get_signal(ticker: str, company_name: str | None = None) -> dict:
    """
    Returns:
        {
            "score": float in [-1, +1],
            "confidence": float in [0, 1],
            "detail": {
                "headline_count": int,
                "summary": str,
            }
        }
    """
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    query = company_name or ticker
    try:
        headlines = _fetch_headlines(query)
    except Exception:
        return {"score": 0.0, "confidence": 0.0, "detail": {"error": "api_unavailable"}}

    result = _score_headlines_with_llm(ticker, headlines, client)
    return {
        "score": round(max(-1.0, min(1.0, result["score"])), 4),
        "confidence": round(max(0.0, min(1.0, result["confidence"])), 4),
        "detail": {
            "headline_count": len(headlines),
            "summary": result["summary"],
        },
    }
