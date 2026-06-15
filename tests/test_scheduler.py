"""Scheduler trade reconciliation tests."""
import os
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ALPACA_API_KEY", "test")
os.environ.setdefault("ALPACA_SECRET_KEY", "test")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.models import Base, Opportunity, Trade  # noqa: E402
from app.scheduler import _execute_judge_trades, sync_open_trades  # noqa: E402


def _session_factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def _exit_order(price: float, qty: float = 2.0) -> dict:
    return {
        "legs": [
            {
                "status": "filled",
                "filled_avg_price": str(price),
                "filled_qty": str(qty),
                "filled_at": "2026-06-15T19:30:00Z",
            }
        ]
    }


def test_sync_open_trades_closes_bullish_trade():
    factory = _session_factory()
    session = factory()
    session.add(Trade(
        ticker="AAPL",
        direction="bullish",
        entry_price=100.0,
        qty=2.0,
        alpaca_order_id="order-1",
        status="open",
    ))
    session.commit()
    session.close()

    with patch("app.trading.alpaca.get_position", return_value=None), \
         patch("app.trading.alpaca.get_order", return_value=_exit_order(105.0)):
        sync_open_trades(factory)

    session = factory()
    trade = session.query(Trade).one()
    assert trade.status == "closed"
    assert trade.exit_price == 105.0
    assert trade.realised_pnl == 10.0
    assert trade.closed_at is not None
    session.close()


def test_sync_open_trades_closes_bearish_trade():
    factory = _session_factory()
    session = factory()
    session.add(Trade(
        ticker="TSLA",
        direction="bearish",
        entry_price=100.0,
        qty=2.0,
        alpaca_order_id="order-2",
        status="open",
    ))
    session.commit()
    session.close()

    with patch("app.trading.alpaca.get_position", return_value=None), \
         patch("app.trading.alpaca.get_order", return_value=_exit_order(95.0)):
        sync_open_trades(factory)

    session = factory()
    trade = session.query(Trade).one()
    assert trade.status == "closed"
    assert trade.exit_price == 95.0
    assert trade.realised_pnl == 10.0
    session.close()


def test_sync_open_trades_updates_and_closes_skipped_opportunity_outcome():
    factory = _session_factory()
    session = factory()
    session.add(Opportunity(
        ticker="AAPL",
        direction="bullish",
        judge_verdict="skip",
        entry_price=100.0,
        outcome_status="open",
    ))
    session.commit()
    session.close()

    with patch("app.trading.alpaca.get_latest_price", return_value=105.0):
        sync_open_trades(factory, close_opportunity_outcomes=True)

    session = factory()
    opp = session.query(Opportunity).one()
    assert opp.outcome_status == "closed"
    assert opp.outcome_price == 105.0
    assert opp.outcome_pnl_pct == 5.0
    assert opp.outcome_recorded_at is not None
    session.close()


def test_execute_judge_trades_places_trade_for_trade_verdict():
    factory = _session_factory()
    session = factory()
    opp = Opportunity(
        ticker="NVDA",
        direction="bullish",
        stocktwits_score=0.7,
        gdelt_score=0.2,
        technical_score=0.4,
        nn_score=0.0,
        fused_score=0.5,
        fused_confidence=0.8,
        judge_verdict="trade",
    )
    session.add(opp)
    session.commit()

    mock_order = {
        "alpaca_order_id": "order-123",
        "entry_price": 100.0,
        "qty": 2.0,
        "notional": 200.0,
        "stop_price": 97.0,
        "target_price": 105.0,
    }
    with patch("app.trading.alpaca.submit_bracket_order", return_value=mock_order) as submit:
        _execute_judge_trades(session, [opp], [{"verdict": "trade"}])

    trade = session.query(Trade).one()
    session.refresh(opp)
    assert opp.traded is True
    assert trade.opportunity_id == opp.id
    assert trade.alpaca_order_id == "order-123"
    submit.assert_called_once_with("NVDA", "bullish", confidence=0.8)
    session.close()
