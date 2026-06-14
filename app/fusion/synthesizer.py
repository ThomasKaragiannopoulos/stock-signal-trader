"""
LLM synthesis: take 3 signal scores + detail and produce a human-readable explanation.
"""
import os
from openai import OpenAI


def synthesize(
    ticker: str,
    polymarket: dict,
    gdelt: dict,
    technical: dict,
    fused_score: float,
    fused_confidence: float,
    direction: str,
) -> str:
    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    tech_detail = technical.get("detail", {})
    poly_detail = polymarket.get("detail", {})
    gdelt_detail = gdelt.get("detail", {})

    prompt = (
        f"You are a quantitative analyst reviewing signals for {ticker}.\n\n"
        f"**Polymarket Signal** (score: {polymarket['score']:+.2f}, confidence: {polymarket['confidence']:.0%})\n"
        f"Market: {poly_detail.get('market_question', 'N/A')}\n"
        f"Implied probability: {poly_detail.get('implied_prob', 'N/A')}\n\n"
        f"**GDELT News Sentiment** (score: {gdelt['score']:+.2f}, confidence: {gdelt['confidence']:.0%})\n"
        f"Based on {gdelt_detail.get('headline_count', 0)} recent headlines.\n"
        f"Summary: {gdelt_detail.get('summary', 'N/A')}\n\n"
        f"**Technical Indicators** (score: {technical['score']:+.2f}, confidence: {technical['confidence']:.0%})\n"
        f"RSI: {tech_detail.get('rsi', 'N/A')} | "
        f"MACD signal: {tech_detail.get('macd_signal', 'N/A')} | "
        f"MA score: {tech_detail.get('ma_score', 'N/A')}\n"
        f"Price: {tech_detail.get('price', 'N/A')} | "
        f"MA20: {tech_detail.get('ma20', 'N/A')} | "
        f"MA50: {tech_detail.get('ma50', 'N/A')}\n\n"
        f"**Fused result**: {direction.upper()} | score {fused_score:+.2f} | confidence {fused_confidence:.0%}\n\n"
        "Write a concise (3-5 sentence) analyst note explaining this opportunity. "
        "Cover what each signal says, whether they agree, and the key risk. "
        "Be direct and factual. No bullet points."
    )

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        max_tokens=250,
        temperature=0.3,
    )
    return response.choices[0].message.content.strip()
