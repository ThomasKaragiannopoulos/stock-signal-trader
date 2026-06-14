import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
load_dotenv()
from datetime import datetime
from typing import Generator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import desc, func, text
from sqlalchemy.orm import Session

from app.models import Base, Opportunity, Trade, get_engine, get_session_factory
from app.scheduler import run_scan, start_scheduler, SCAN_STATUS
from app.trading import alpaca
from app.signals import stocktwits, gdelt, technical, nn_signal
from app.fusion import aggregator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

engine = get_engine(os.getenv("DATABASE_URL", "sqlite:///./trader.db"))
Base.metadata.create_all(engine)
_SessionFactory = get_session_factory(engine)


def get_db() -> Generator[Session, None, None]:
    session = _SessionFactory()
    try:
        yield session
    finally:
        session.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    nn_signal.load_model()
    scheduler = start_scheduler(_SessionFactory)
    yield
    scheduler.shutdown()


app = FastAPI(title="Stock Signal Trader", lifespan=lifespan)

_cors_origins = [o.strip() for o in os.getenv("CORS_ORIGINS", "").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Opportunities ─────────────────────────────────────────────────────────────

@app.get("/opportunities")
def list_opportunities(db: Session = Depends(get_db)):
    # Latest scanned_at per ticker, then fetch those rows
    latest_per_ticker = (
        db.query(Opportunity.ticker, func.max(Opportunity.scanned_at).label("max_ts"))
        .group_by(Opportunity.ticker)
        .subquery()
    )
    rows = (
        db.query(Opportunity)
        .join(
            latest_per_ticker,
            (Opportunity.ticker == latest_per_ticker.c.ticker)
            & (Opportunity.scanned_at == latest_per_ticker.c.max_ts),
        )
        .order_by(desc(Opportunity.fused_confidence))
        .all()
    )
    return [_opportunity_to_dict(o) for o in rows]


# ── Execute trade ─────────────────────────────────────────────────────────────

@app.post("/trade/{opportunity_id}")
def execute_trade(opportunity_id: int, db: Session = Depends(get_db)):
    opp = db.query(Opportunity).filter_by(id=opportunity_id).first()
    if opp is None:
        raise HTTPException(status_code=404, detail="Opportunity not found")
    if opp.traded:
        raise HTTPException(status_code=400, detail="Already traded")
    if opp.direction == "neutral":
        raise HTTPException(status_code=400, detail="Cannot trade neutral signal")

    order = alpaca.submit_bracket_order(opp.ticker, opp.direction)

    trade = Trade(
        opportunity_id=opp.id,
        ticker=opp.ticker,
        direction=opp.direction,
        entry_price=order["entry_price"],
        qty=order["qty"],
        notional=order["notional"],
        stop_price=order["stop_price"],
        target_price=order["target_price"],
        alpaca_order_id=order["alpaca_order_id"],
        signal_scores={
            "stocktwits": opp.stocktwits_score,
            "gdelt": opp.gdelt_score,
            "technical": opp.technical_score,
            "fused": opp.fused_score,
            "confidence": opp.fused_confidence,
        },
    )
    opp.traded = True
    db.add(trade)
    db.commit()
    db.refresh(trade)
    return _trade_to_dict(trade)


# ── Portfolio ─────────────────────────────────────────────────────────────────

@app.get("/portfolio")
def portfolio():
    try:
        positions = alpaca.get_positions()
        account = alpaca.get_account()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca error: {e}")

    return {
        "equity": float(account["equity"]),
        "cash": float(account["cash"]),
        "positions": [
            {
                "ticker": p["symbol"],
                "qty": float(p["qty"]),
                "side": p["side"],
                "entry_price": float(p["avg_entry_price"]),
                "current_price": float(p["current_price"]),
                "unrealised_pnl": float(p["unrealized_pl"]),
                "unrealised_pnl_pct": float(p["unrealized_plpc"]) * 100,
                "market_value": float(p["market_value"]),
            }
            for p in positions
        ],
    }


# ── History ───────────────────────────────────────────────────────────────────

@app.get("/history")
def history(db: Session = Depends(get_db)):
    trades = (
        db.query(Trade)
        .filter_by(status="closed")
        .order_by(desc(Trade.closed_at))
        .all()
    )
    return [_trade_to_dict(t) for t in trades]


# ── Scan status ───────────────────────────────────────────────────────────────

@app.get("/scan/status")
def scan_status():
    return SCAN_STATUS


# ── Manual scan trigger ───────────────────────────────────────────────────────

@app.get("/health")
def health(db: Session = Depends(get_db)):
    db.execute(text("SELECT 1"))
    return {"status": "ok"}


@app.post("/scan")
def trigger_scan(ticker: str = Query(default=None)):
    try:
        tickers = [ticker.upper()] if ticker else None
        run_scan(_SessionFactory, tickers=tickers)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "scan complete", "timestamp": datetime.utcnow().isoformat()}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _opportunity_to_dict(o: Opportunity) -> dict:
    return {
        "id": o.id,
        "ticker": o.ticker,
        "scanned_at": o.scanned_at.isoformat() if o.scanned_at else None,
        "signals": {
            "stocktwits": {"score": o.stocktwits_score, "confidence": o.stocktwits_confidence},
            "gdelt": {"score": o.gdelt_score, "confidence": o.gdelt_confidence},
            "technical": {"score": o.technical_score, "confidence": o.technical_confidence},
            "nn": {"score": o.nn_score, "confidence": o.nn_confidence},
        },
        "fused_score": o.fused_score,
        "fused_confidence": o.fused_confidence,
        "direction": o.direction,
        "llm_explanation": o.llm_explanation,
        "judge_verdict": o.judge_verdict,
        "judge_reason": o.judge_reason,
        "signal_detail": o.signal_detail,
        "traded": bool(o.traded),
    }


def _trade_to_dict(t: Trade) -> dict:
    return {
        "id": t.id,
        "opportunity_id": t.opportunity_id,
        "ticker": t.ticker,
        "direction": t.direction,
        "executed_at": t.executed_at.isoformat() if t.executed_at else None,
        "entry_price": t.entry_price,
        "qty": t.qty,
        "notional": t.notional,
        "stop_price": t.stop_price,
        "target_price": t.target_price,
        "alpaca_order_id": t.alpaca_order_id,
        "status": t.status,
        "exit_price": t.exit_price,
        "realised_pnl": t.realised_pnl,
        "closed_at": t.closed_at.isoformat() if t.closed_at else None,
        "signal_scores": t.signal_scores,
    }


# ── Debug: raw signals for one ticker ─────────────────────────────────────────

@app.get("/debug/{ticker}")
def debug_ticker(ticker: str):
    from app.scheduler import TICKER_TO_COMPANY
    company = TICKER_TO_COMPANY.get(ticker.upper(), ticker.upper())
    st = stocktwits.get_signal(ticker.upper())
    gdelt_sig = gdelt.get_signal(ticker.upper(), company)
    tech = technical.get_signal(ticker.upper())
    fusion = aggregator.fuse(st, gdelt_sig, tech)
    return {"ticker": ticker.upper(), "stocktwits": st, "gdelt": gdelt_sig, "technical": tech, "fusion": fusion}


# ── Static frontend ───────────────────────────────────────────────────────────

app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
