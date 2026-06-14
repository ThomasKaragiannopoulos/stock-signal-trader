"""
LLM as judge: sees all 4 signal scores + the LLM summary and decides trade/skip.
Single batched call per scan — one verdict per opportunity.
"""
import json
import logging
import os

from openai import OpenAI

logger = logging.getLogger(__name__)


def batch_judge(items: list[dict], client: OpenAI | None = None) -> list[dict]:
    """
    Args:
        items: list of dicts with keys:
            ticker, st_score, st_conf, gdelt_score, gdelt_conf,
            tech_score, tech_conf, nn_score, nn_conf, nn_status, nn_trades,
            fused_score, fused_confidence, direction, summary
    Returns:
        list of {"verdict": "trade"|"skip", "reason": str}
    """
    if not items:
        return []

    if client is None:
        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])

    sections = []
    for i, o in enumerate(items):
        nn_note = (
            f"NN p(profit)={o['nn_detail'].get('p_profit', 'n/a')} on {o['nn_detail'].get('n_trades', 0)} trades"
            if o["nn_detail"].get("status") == "active"
            else f"NN: no model yet ({o['nn_detail'].get('n_trades', 0)} trades so far)"
        )
        sections.append(
            f"{i}. {o['ticker']} — {o['direction'].upper()} "
            f"fused_score={o['fused_score']:+.2f} confidence={o['fused_confidence']:.0%}\n"
            f"   StockTwits : score={o['st_score']:+.2f}  conf={o['st_conf']:.0%}\n"
            f"   GDELT news : score={o['gdelt_score']:+.2f}  conf={o['gdelt_conf']:.0%}\n"
            f"   Technical  : score={o['tech_score']:+.2f}  conf={o['tech_conf']:.0%}\n"
            f"   {nn_note}\n"
            f"   Summary: {o['summary']}"
        )

    prompt = (
        "You are a trading risk officer making final go/no-go decisions.\n"
        "For each stock, decide 'trade' or 'skip' based on all four signal scores and the summary.\n"
        "Be selective — only say 'trade' when signals meaningfully agree and confidence is solid.\n"
        "Give one short plain-English sentence explaining your decision.\n"
        "Respond with a JSON object: "
        "{\"verdicts\": [{\"verdict\": \"trade\"|\"skip\", \"reason\": \"...\"}]}\n\n"
        + "\n\n".join(sections)
    )

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=max(150, 80 * len(items)),
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        verdicts = json.loads(resp.choices[0].message.content).get("verdicts", [])
    except Exception:
        logger.exception("Judge: LLM call failed")
        verdicts = []

    results = []
    for i, o in enumerate(items):
        if i < len(verdicts) and verdicts[i].get("verdict") in ("trade", "skip"):
            results.append({
                "verdict": verdicts[i]["verdict"],
                "reason": verdicts[i].get("reason", ""),
            })
        else:
            results.append({"verdict": "skip", "reason": "Signals not strong enough."})
    return results
