"""
APScheduler: daily morning scan at 09:00 EST + EOD close at 15:55 EST.
Scan uses batched LLM calls: 3 total instead of ~60.
"""
import json
import logging
import os
import threading
import time
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from openai import OpenAI

from app.signals import stocktwits, gdelt, technical, nn_signal
from app.fusion import aggregator, synthesizer, judge
from app.models import Opportunity, get_engine, get_session_factory
from app.trading import alpaca

logger = logging.getLogger(__name__)

WATCHLIST_PATH = Path(__file__).parent.parent / "watchlist.json"

# ticker → full company name, sourced from watchlist.json
TICKER_TO_COMPANY: dict[str, str] = json.loads(WATCHLIST_PATH.read_text())

_GDELT_DELAY = 1.5  # seconds between tickers to avoid GDELT IP rate limit

_scan_lock = threading.Lock()

SCAN_STATUS: dict = {
    "running": False, "phase": 0, "phase_label": "idle",
    "tickers_total": 0, "tickers_fetched": 0, "opportunities": 0, "live_tickers": [],
    "failed_tickers": [],
}


def run_scan(session_factory=None, tickers: list[str] | None = None):
    """
    Scan all watchlist tickers using batched LLM calls.

    Phases:
      1. Fetch all StockTwits posts + GDELT headlines (HTTP, no LLM)
      2. One LLM call — score StockTwits sentiment for all tickers
      3. One LLM call — score GDELT sentiment for all tickers
      4. Technical indicators + NN + fusion (local, no API)
      5. One LLM call — synthesize explanations for opportunities only
      6. One LLM call — judge makes trade/skip decisions
    """
    if session_factory is None:
        engine = get_engine()
        session_factory = get_session_factory(engine)

    if not _scan_lock.acquire(blocking=False):
        logger.warning("Scan already in progress — skipping concurrent request")
        return

    client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
    watchlist = tickers if tickers else list(TICKER_TO_COMPANY.keys())
    session = session_factory()

    SCAN_STATUS.update({
        "running": True, "phase": 1, "phase_label": "Fetching market & news data",
        "tickers_total": len(watchlist), "tickers_fetched": 0, "opportunities": 0, "live_tickers": [],
    })

    try:
        scan_started_at = time.monotonic()
        # ── Phase 1: Fetch HTTP data ───────────────────────────────────────
        logger.info("Phase 1: fetching market + news data for %d tickers", len(watchlist))
        ticker_data = []
        for ticker in watchlist:
            company = TICKER_TO_COMPANY.get(ticker, ticker)
            st_posts = stocktwits.fetch_posts(ticker)
            gdelt_headlines = gdelt.fetch_articles(ticker, company)
            ticker_data.append({
                "ticker": ticker,
                "company": company,
                "st_posts": st_posts,
                "gdelt_headlines": gdelt_headlines,
            })
            SCAN_STATUS["tickers_fetched"] += 1
            SCAN_STATUS["live_tickers"].append(ticker)
            time.sleep(_GDELT_DELAY)

        SCAN_STATUS.update({"phase": 2, "phase_label": "Scoring StockTwits trader sentiment (LLM)"})

        # ── Phase 2: Batch LLM — StockTwits sentiment ─────────────────────
        logger.info("Phase 2: batch StockTwits LLM (%d tickers)", len(ticker_data))
        st_signals = stocktwits.batch_score(
            [{"ticker": d["ticker"], "posts": d["st_posts"]} for d in ticker_data],
            client,
        )

        SCAN_STATUS.update({"phase": 3, "phase_label": "Scoring news sentiment (LLM)"})

        # ── Phase 3: Batch LLM — GDELT sentiment ──────────────────────────
        logger.info("Phase 3: batch GDELT LLM (%d tickers)", len(ticker_data))
        gdelt_signals = gdelt.batch_score(
            [{"ticker": d["ticker"], "headlines": d["gdelt_headlines"]} for d in ticker_data],
            client,
        )

        SCAN_STATUS.update({"phase": 4, "phase_label": "Computing technical indicators, NN & fusion"})

        # ── Phase 4: Technical + NN + fusion ──────────────────────────────
        logger.info("Phase 4: technical signals + NN + fusion")
        nn_signal.maybe_retrain(session)
        opportunities = []
        failed_tickers = []
        for i, d in enumerate(ticker_data):
            ticker = d["ticker"]
            try:
                tech = technical.get_signal(ticker)
                st_sig = st_signals[i] if i < len(st_signals) else {"score": 0.0, "confidence": 0.0, "detail": {}}
                gdelt_sig = gdelt_signals[i] if i < len(gdelt_signals) else {"score": 0.0, "confidence": 0.0, "detail": {}}
                nn_sig = nn_signal.get_signal(st_sig["score"], gdelt_sig["score"], tech["score"])
                fusion = aggregator.fuse(st_sig, gdelt_sig, tech, nn_sig)

                logger.info("%s: %s %.0f%%", ticker, fusion["direction"], fusion["fused_confidence"] * 100)
                opportunities.append({
                    "ticker": ticker,
                    "stocktwits": st_sig,
                    "gdelt": gdelt_sig,
                    "technical": tech,
                    "nn": nn_sig,
                    "fusion": fusion,
                    "st_posts": d["st_posts"],
                    "gdelt_headlines": d["gdelt_headlines"],
                })
            except Exception:
                logger.exception("Error processing %s", ticker)
                failed_tickers.append(ticker)

        SCAN_STATUS["opportunities"] = len(opportunities)

        if not opportunities:
            logger.info("Scan complete: no opportunities found")
            session.close()
            return

        if time.monotonic() - scan_started_at > 1200:
            logger.warning("Scan has been running for >20 minutes before Phase 5")

        # ── Phase 5: Batch LLM — synthesis ────────────────────────────────
        SCAN_STATUS.update({"phase": 5, "phase_label": "Generating summaries (LLM)"})
        logger.info("Phase 5: synthesizing %d opportunities", len(opportunities))
        explanations = synthesizer.batch_synthesize(
            [
                {
                    "ticker": o["ticker"],
                    "stocktwits": o["stocktwits"],
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

        # ── Phase 6: Batch LLM — judge ────────────────────────────────────
        SCAN_STATUS.update({"phase": 6, "phase_label": "LLM judge making trade decisions"})
        logger.info("Phase 6: judge evaluating %d opportunities", len(opportunities))
        judge_results = judge.batch_judge(
            [
                {
                    "ticker": o["ticker"],
                    "st_score": o["stocktwits"]["score"],
                    "st_conf": o["stocktwits"]["confidence"],
                    "gdelt_score": o["gdelt"]["score"],
                    "gdelt_conf": o["gdelt"]["confidence"],
                    "tech_score": o["technical"]["score"],
                    "tech_conf": o["technical"]["confidence"],
                    "nn_score": o["nn"]["score"],
                    "nn_conf": o["nn"]["confidence"],
                    "nn_detail": o["nn"]["detail"],
                    "fused_score": o["fusion"]["fused_score"],
                    "fused_confidence": o["fusion"]["fused_confidence"],
                    "direction": o["fusion"]["direction"],
                    "summary": explanations[j],
                }
                for j, o in enumerate(opportunities)
            ],
            client,
        )

        for o, explanation, verdict in zip(opportunities, explanations, judge_results):
            opp = Opportunity(
                ticker=o["ticker"],
                stocktwits_score=o["stocktwits"]["score"],
                stocktwits_confidence=o["stocktwits"]["confidence"],
                gdelt_score=o["gdelt"]["score"],
                gdelt_confidence=o["gdelt"]["confidence"],
                technical_score=o["technical"]["score"],
                technical_confidence=o["technical"]["confidence"],
                nn_score=o["nn"]["score"],
                nn_confidence=o["nn"]["confidence"],
                fused_score=o["fusion"]["fused_score"],
                fused_confidence=o["fusion"]["fused_confidence"],
                direction=o["fusion"]["direction"],
                llm_explanation=explanation,
                judge_verdict=verdict["verdict"],
                judge_reason=verdict["reason"],
                signal_detail={
                    "stocktwits": {**o["stocktwits"]["detail"], "posts": o["st_posts"]},
                    "gdelt": {**o["gdelt"]["detail"], "headlines": o["gdelt_headlines"]},
                    "technical": o["technical"]["detail"],
                    "nn": o["nn"]["detail"],
                },
            )
            session.add(opp)

        try:
            session.commit()
        except Exception:
            logger.exception("Failed to commit opportunities")
            session.rollback()

        SCAN_STATUS["failed_tickers"] = failed_tickers
        if failed_tickers:
            logger.warning("Scan completed with %d failures: %s", len(failed_tickers), failed_tickers)

        session.close()
        logger.info("Scan complete: %d opportunities saved", len(opportunities))

    finally:
        SCAN_STATUS.update({"running": False, "phase": 0, "phase_label": "idle"})
        _scan_lock.release()


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
            logger.exception("EOD: failed to sync trade status for %s", trade.ticker)
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
