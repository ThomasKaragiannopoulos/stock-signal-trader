"""
APScheduler: daily morning scan at 09:00 EST + EOD close at 15:55 EST.
Scan uses batched LLM calls: 3 total instead of ~60.
"""
import json
import logging
import os
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from openai import OpenAI

from app.signals import polymarket, gdelt, technical
from app.fusion import aggregator, synthesizer
from app.models import Opportunity, get_engine, get_session_factory
from app.trading import alpaca

logger = logging.getLogger(__name__)

WATCHLIST_PATH = Path(__file__).parent.parent / "watchlist.json"

SCAN_STATUS: dict = {"running": False, "phase": 0, "phase_label": "idle", "tickers_total": 0, "tickers_fetched": 0, "opportunities": 0}

TICKER_TO_COMPANY = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet Google",
    "AMZN": "Amazon", "NVDA": "Nvidia", "META": "Meta Facebook",
    "TSLA": "Tesla", "JPM": "JPMorgan Chase", "V": "Visa", "MA": "Mastercard",
    "UNH": "UnitedHealth", "HD": "Home Depot", "PG": "Procter Gamble",
    "JNJ": "Johnson Johnson", "XOM": "ExxonMobil", "BAC": "Bank of America",
    "DIS": "Disney", "NFLX": "Netflix", "AMD": "AMD", "PYPL": "PayPal",
}


def run_scan(session_factory=None):
    """
    Scan all watchlist tickers using batched LLM calls.

    Phases:
      1. Fetch all Polymarket markets + GDELT headlines (HTTP, no LLM)
      2. One LLM call — pick best Polymarket market for all tickers
      3. One LLM call — score GDELT sentiment for all tickers
      4. Technical indicators + fusion (local, no API)
      5. One LLM call — synthesize explanations for opportunities only
    """
    if session_factory is None:
        engine = get_engine()
        session_factory = get_session_factory(engine)

    if SCAN_STATUS["running"]:
        logger.warning("Scan already in progress — skipping concurrent request")
        return

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    watchlist = json.loads(WATCHLIST_PATH.read_text())
    session = session_factory()

    SCAN_STATUS.update({"running": True, "phase": 1, "phase_label": "Fetching market & news data", "tickers_total": len(watchlist), "tickers_fetched": 0, "opportunities": 0})

    # ── Phase 1: Fetch HTTP data ───────────────────────────────────────────
    logger.info("Phase 1: fetching market + news data for %d tickers", len(watchlist))
    ticker_data = []
    for ticker in watchlist:
        company = TICKER_TO_COMPANY.get(ticker, ticker)
        ticker_data.append({
            "ticker": ticker,
            "company": company,
            "poly_markets": polymarket.fetch_markets(ticker, company),
            "gdelt_headlines": gdelt.fetch_articles(ticker, company),
        })
        SCAN_STATUS["tickers_fetched"] += 1

    SCAN_STATUS.update({"phase": 2, "phase_label": "Analyzing Polymarket signals (LLM)"})

    # ── Phase 2: Batch LLM — Polymarket picks ─────────────────────────────
    logger.info("Phase 2: batch Polymarket LLM (%d tickers)", len(ticker_data))
    poly_signals = polymarket.batch_score(
        [{"ticker": d["ticker"], "markets": d["poly_markets"]} for d in ticker_data],
        client,
    )

    SCAN_STATUS.update({"phase": 3, "phase_label": "Scoring news sentiment (LLM)"})

    # ── Phase 3: Batch LLM — GDELT sentiment ──────────────────────────────
    logger.info("Phase 3: batch GDELT LLM (%d tickers)", len(ticker_data))
    gdelt_signals = gdelt.batch_score(
        [{"ticker": d["ticker"], "headlines": d["gdelt_headlines"]} for d in ticker_data],
        client,
    )

    SCAN_STATUS.update({"phase": 4, "phase_label": "Computing technical indicators & fusion"})

    # ── Phase 4: Technical + fusion ───────────────────────────────────────
    logger.info("Phase 4: technical signals + fusion")
    opportunities = []
    for i, d in enumerate(ticker_data):
        ticker = d["ticker"]
        try:
            tech = technical.get_signal(ticker)
            poly_sig = poly_signals[i] if i < len(poly_signals) else {"score": 0.0, "confidence": 0.0, "detail": {}}
            gdelt_sig = gdelt_signals[i] if i < len(gdelt_signals) else {"score": 0.0, "confidence": 0.0, "detail": {}}
            fusion = aggregator.fuse(poly_sig, gdelt_sig, tech)

            if not fusion["opportunity"]:
                logger.info("%s: confidence %.0f%% — skipping", ticker, fusion["fused_confidence"] * 100)
                continue

            logger.info("%s: %s %.0f%%", ticker, fusion["direction"], fusion["fused_confidence"] * 100)
            opportunities.append({
                "ticker": ticker,
                "polymarket": poly_sig,
                "gdelt": gdelt_sig,
                "technical": tech,
                "fusion": fusion,
            })
        except Exception:
            logger.exception("Error processing %s", ticker)

    # ── Phase 5: Batch LLM — synthesis ────────────────────────────────────
    SCAN_STATUS["opportunities"] = len(opportunities)

    if not opportunities:
        logger.info("Scan complete: no opportunities found")
        SCAN_STATUS.update({"running": False, "phase": 0, "phase_label": "idle"})
        session.close()
        return

    SCAN_STATUS.update({"phase": 5, "phase_label": f"Generating explanations for {len(opportunities)} opportunities (LLM)"})
    logger.info("Phase 5: synthesizing %d opportunities", len(opportunities))
    explanations = synthesizer.batch_synthesize(
        [
            {
                "ticker": o["ticker"],
                "polymarket": o["polymarket"],
                "gdelt": o["gdelt"],
                "technical": o["technical"],
                "fused_score": o["fusion"]["fused_score"],
                "fused_confidence": o["fusion"]["fused_confidence"],
                "direction": o["fusion"]["direction"],
            }
            for o in opportunities
        ],
        client,
    )

    for o, explanation in zip(opportunities, explanations):
        opp = Opportunity(
            ticker=o["ticker"],
            polymarket_score=o["polymarket"]["score"],
            polymarket_confidence=o["polymarket"]["confidence"],
            gdelt_score=o["gdelt"]["score"],
            gdelt_confidence=o["gdelt"]["confidence"],
            technical_score=o["technical"]["score"],
            technical_confidence=o["technical"]["confidence"],
            fused_score=o["fusion"]["fused_score"],
            fused_confidence=o["fusion"]["fused_confidence"],
            direction=o["fusion"]["direction"],
            llm_explanation=explanation,
            signal_detail={
                "polymarket": o["polymarket"]["detail"],
                "gdelt": o["gdelt"]["detail"],
                "technical": o["technical"]["detail"],
            },
        )
        session.add(opp)

    try:
        session.commit()
    except Exception:
        logger.exception("Failed to commit opportunities")
        session.rollback()

    session.close()
    SCAN_STATUS.update({"running": False, "phase": 0, "phase_label": "idle"})
    logger.info("Scan complete: %d opportunities saved", len(opportunities))


def run_eod_close(session_factory=None):
    """Close all open positions and mark trades closed."""
    if session_factory is None:
        engine = get_engine()
        session_factory = get_session_factory(engine)

    try:
        alpaca.close_all_eod()
        logger.info("EOD: closed all positions")
    except Exception:
        logger.exception("EOD close failed")

    from app.models import Trade
    session = session_factory()
    for trade in session.query(Trade).filter_by(status="open").all():
        try:
            if alpaca.get_position(trade.ticker) is None:
                trade.status = "closed"
        except Exception:
            pass
    session.commit()
    session.close()


def start_scheduler(session_factory=None) -> BackgroundScheduler:
    scheduler = BackgroundScheduler(timezone="America/New_York")
    scheduler.add_job(
        lambda: run_scan(session_factory),
        CronTrigger(hour=9, minute=0),
        id="morning_scan",
    )
    scheduler.add_job(
        lambda: run_eod_close(session_factory),
        CronTrigger(hour=15, minute=55),
        id="eod_close",
    )
    scheduler.start()
    return scheduler
