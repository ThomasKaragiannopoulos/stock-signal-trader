"""
LLM synthesis: take 3 signal scores + detail and produce human-readable explanations.
Supports batched calls to minimize API round-trips.
"""
import json
import os

from openai import OpenAI


def batch_synthesize(items: list[dict], client: OpenAI | None = None) -> list[str]:
    """
    Single LLM call to synthesize explanations for multiple opportunities.

    Args:
        items: list of dicts with keys: ticker, polymarket, gdelt, technical,
               fused_score, fused_confidence, direction
    Returns:
        list of explanation strings in same order
    """
    if not items:
        return []

    if client is None:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    sections = []
    for i, o in enumerate(items):
        td = o["technical"].get("detail", {})
        pd = o["polymarket"].get("detail", {})
        gd = o["gdelt"].get("detail", {})
        sections.append(
            f"{i}. {o['ticker']} — {o['direction'].upper()} {o['fused_confidence']:.0%}\n"
            f"   Polymarket: score={o['polymarket']['score']:+.2f} conf={o['polymarket']['confidence']:.0%}"
            f" market={pd.get('market_question', 'none')}\n"
            f"   GDELT: score={o['gdelt']['score']:+.2f} conf={o['gdelt']['confidence']:.0%}"
            f" ({gd.get('headline_count', 0)} headlines) {gd.get('summary', '')}\n"
            f"   Technical: RSI={td.get('rsi', 'n/a')} score={o['technical']['score']:+.2f}"
            f" conf={o['technical']['confidence']:.0%} price={td.get('price', 'n/a')}"
            f" MA20={td.get('ma20', 'n/a')} MA50={td.get('ma50', 'n/a')}"
        )

    prompt = (
        "For each stock below write exactly 2 short plain-English sentences: what the signals say and the key risk. "
        "No intro, no 'Based on...', no analyst jargon. Write like you're texting a friend who trades.\n"
        "Respond with a JSON object: {\"explanations\": [\"...\", \"...\"]} one string per stock.\n\n"
        + "\n\n".join(sections)
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250 * len(items),
            temperature=0.3,
            response_format={"type": "json_object"},
        )
        explanations = json.loads(resp.choices[0].message.content).get("explanations", [])
    except Exception:
        explanations = []

    result = []
    for i, o in enumerate(items):
        if i < len(explanations) and explanations[i]:
            result.append(explanations[i])
        else:
            result.append(
                f"{o['ticker']} shows a {o['direction']} signal with {o['fused_confidence']:.0%} confidence."
            )
    return result


def synthesize(
    ticker: str,
    polymarket: dict,
    gdelt: dict,
    technical: dict,
    fused_score: float,
    fused_confidence: float,
    direction: str,
) -> str:
    """Single-ticker interface — used by tests and /debug endpoint."""
    return batch_synthesize([{
        "ticker": ticker,
        "polymarket": polymarket,
        "gdelt": gdelt,
        "technical": technical,
        "fused_score": fused_score,
        "fused_confidence": fused_confidence,
        "direction": direction,
    }])[0]
