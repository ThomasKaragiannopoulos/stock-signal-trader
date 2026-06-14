"""
StockTwits signal: fetch recent trader posts for a ticker,
use LLM (batched) to score sentiment from human-language posts + explicit bullish/bearish tags.
"""
import json
import os

import httpx
from openai import OpenAI

_NEUTRAL = {"score": 0.0, "confidence": 0.0, "detail": {"post_count": 0, "summary": "no data"}}


def fetch_posts(ticker: str) -> list[dict]:
    """HTTP only — fetch StockTwits posts for ticker. Returns [] on error or rate limit."""
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        resp = httpx.get(url, timeout=10)
        if resp.status_code in (429, 403):
            return []
        resp.raise_for_status()
        messages = resp.json().get("messages", []) or []
        return [
            {
                "body": m.get("body", ""),
                "sentiment": (m.get("entities") or {}).get("sentiment", {}).get("basic", ""),
            }
            for m in messages[:20]
            if m.get("body")
        ]
    except Exception:
        return []


def batch_score(ticker_posts: list[dict], client: OpenAI) -> list[dict]:
    """
    Single LLM call to score StockTwits sentiment for all tickers.

    Args:
        ticker_posts: list of {"ticker": str, "posts": list[dict]}
    Returns:
        list of signal dicts in same order
    """
    if not ticker_posts:
        return []

    sections = []
    for i, item in enumerate(ticker_posts):
        if not item["posts"]:
            sections.append(f"{i}. {item['ticker']}: no posts")
        else:
            lines = []
            for p in item["posts"]:
                tag = f" [{p['sentiment']}]" if p.get("sentiment") else ""
                lines.append(f"  - {p['body']}{tag}")
            sections.append(f"{i}. {item['ticker']}:\n" + "\n".join(lines))

    prompt = (
        "You are analyzing trader sentiment from StockTwits posts. "
        "Posts may include explicit [Bullish] or [Bearish] tags set by the poster.\n"
        "For each ticker, score the overall sentiment for near-term price direction.\n"
        "Return {\"results\": [...]} where each element is "
        "{\"score\": float (-1.0 to 1.0), \"confidence\": float (0.0 to 1.0), \"summary\": str (1 sentence)}.\n"
        "Score: -1.0 = strongly bearish, 0.0 = neutral/mixed, +1.0 = strongly bullish.\n"
        "Confidence: higher when posts are consistent and numerous, lower when mixed or sparse.\n\n"
        + "\n\n".join(sections)
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100 * len(ticker_posts),
            temperature=0,
            response_format={"type": "json_object"},
        )
        results = json.loads(resp.choices[0].message.content).get("results", [])
    except Exception:
        results = []

    signals = []
    for i, item in enumerate(ticker_posts):
        posts = item["posts"]
        if not posts or i >= len(results):
            signals.append(_NEUTRAL.copy())
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
            "detail": {"post_count": len(posts), "summary": summary},
        })

    return signals


def get_signal(ticker: str, company_name: str | None = None) -> dict:
    """Single-ticker interface — used by tests and /debug endpoint."""
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    posts = fetch_posts(ticker)
    return batch_score([{"ticker": ticker, "posts": posts}], client)[0]
