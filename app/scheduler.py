"""
APScheduler: daily morning scan at 09:00 EST + EOD close at 15:55 EST.
"""
import json
import logging
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from app.signals import polymarket, gdelt, technical
from app.fusion import aggregator, synthesizer
from app.models import Opportunity, get_engine, get_session_factory
from app.trading import alpaca

logger = logging.getLogger(__name__)

WATCHLIST_PATH = Path(__file__).parent.parent / "watchlist.json"

TICKER_TO_COMPANY = {
    "AAPL": "Apple", "MSFT": "Microsoft", "GOOGL": "Alphabet Google",
    "AMZN": "Amazon", "NVDA": "Nvidia", "META": "Meta Facebook",
    "TSLA": "Tesla", "JPM": "JPMorgan Chase", "V": "Visa", "MA": "Mastercard",
    "UNH": "UnitedHealth", "HD": "Home Depot", "PG": "Procter Gamble",
    "JNJ": "Johnson Johnson", "XOM": "ExxonMobil", "BAC": "Bank of America",
    "DIS": "Disney", "NFLX": "Netflix", "AMD": "AMD", "PYPL": "PayPal",
}


def run_scan(session_factory=None):
    """Scan all watchlist tickers and persist opportunities."""
    if session_factory is None:
        engine = get_engine()
        session_factory = get_session_factory(engine)

    watchlist = json.loads(WATCHLIST_PATH.read_text())
    session = session_factory()

    for ticker in watchlist:
        company = TICKER_TO_COMPANY.get(ticker, ticker)
        logger.info("Scanning %s", ticker)
        try:
            poly = polymarket.get_signal(ticker, company)
            gdelt_sig = gdelt.get_signal(ticker, company)
            tech = technical.get_signal(ticker)

            fusion = aggregator.fuse(poly, gdelt_sig, tech)
            if not fusion["opportunity"]:
                logger.info("%s: confidence %.0f%% — skipping", ticker, fusion["fused_confidence"] * 100)
                continue

            explanation = synthesizer.synthesize(
                ticker=ticker,
                polymarket=poly,
                gdelt=gdelt_sig,
                technical=tech,
                fused_score=fusion["fused_score"],
                fused_confidence=fusion["fused_confidence"],
                direction=fusion["direction"],
            )

            opp = Opportunity(
                ticker=ticker,
                polymarket_score=poly["score"],
                polymarket_confidence=poly["confidence"],
                gdelt_score=gdelt_sig["score"],
                gdelt_confidence=gdelt_sig["confidence"],
                technical_score=tech["score"],
                technical_confidence=tech["confidence"],
                fused_score=fusion["fused_score"],
                fused_confidence=fusion["fused_confidence"],
                direction=fusion["direction"],
                llm_explanation=explanation,
                signal_detail={
                    "polymarket": poly["detail"],
                    "gdelt": gdelt_sig["detail"],
                    "technical": tech["detail"],
                },
            )
            session.add(opp)
            session.commit()
            logger.info("%s: %s %.0f%%", ticker, fusion["direction"], fusion["fused_confidence"] * 100)
        except Exception:
            logger.exception("Error scanning %s", ticker)
            session.rollback()

    session.close()


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
    open_trades = session.query(Trade).filter_by(status="open").all()
    for trade in open_trades:
        try:
            pos = alpaca.get_position(trade.ticker)
            if pos is None:
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
