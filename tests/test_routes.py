"""FastAPI route tests using TestClient with in-memory SQLite and dependency overrides."""
import os
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.pool import StaticPool

os.environ.setdefault("OPENAI_API_KEY", "test")
os.environ.setdefault("ALPACA_API_KEY", "test")
os.environ.setdefault("ALPACA_SECRET_KEY", "test")
os.environ["DATABASE_URL"] = "sqlite:///:memory:"

from app.models import Base, Opportunity  # noqa: E402
from app.main import app, get_db  # noqa: E402

# ── In-memory DB shared across all route tests ────────────────────────────────

_test_engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,  # all connections share the same in-memory DB
)
Base.metadata.create_all(_test_engine)
_TestSession = sessionmaker(bind=_test_engine)


def override_get_db():
    session = _TestSession()
    try:
        yield session
    finally:
        session.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="module")
def client():
    mock_scheduler = MagicMock()
    mock_scheduler.shutdown = MagicMock()
    with patch("app.main.start_scheduler", return_value=mock_scheduler), \
         patch("app.main.nn_signal.load_model"):
        with TestClient(app) as c:
            yield c


# ── Tests ─────────────────────────────────────────────────────────────────────

def test_opportunities_empty(client):
    resp = client.get("/opportunities")
    assert resp.status_code == 200
    assert resp.json() == []


def test_opportunities_with_data(client):
    session = _TestSession()
    opp = Opportunity(
        ticker="AAPL",
        stocktwits_score=0.6,
        stocktwits_confidence=0.7,
        gdelt_score=0.5,
        gdelt_confidence=0.6,
        technical_score=0.4,
        technical_confidence=0.5,
        fused_score=0.52,
        fused_confidence=0.62,
        direction="bullish",
        llm_explanation="Strong buy signal.",
        signal_detail={},
    )
    session.add(opp)
    session.commit()
    session.close()

    resp = client.get("/opportunities")
    assert resp.status_code == 200
    data = resp.json()
    assert any(d["ticker"] == "AAPL" for d in data)
    aapl = next(d for d in data if d["ticker"] == "AAPL")
    assert aapl["direction"] == "bullish"


def test_trade_not_found(client):
    resp = client.post("/trade/9999")
    assert resp.status_code == 404


def test_trade_neutral_rejected(client):
    session = _TestSession()
    opp = Opportunity(
        ticker="MSFT",
        stocktwits_score=0.0,
        stocktwits_confidence=0.5,
        gdelt_score=0.0,
        gdelt_confidence=0.5,
        technical_score=0.0,
        technical_confidence=0.5,
        fused_score=0.0,
        fused_confidence=0.55,
        direction="neutral",
        llm_explanation="No clear direction.",
        signal_detail={},
    )
    session.add(opp)
    session.commit()
    opp_id = opp.id
    session.close()

    resp = client.post(f"/trade/{opp_id}")
    assert resp.status_code == 400
    assert "neutral" in resp.json()["detail"]


def test_trade_executes(client):
    session = _TestSession()
    opp = Opportunity(
        ticker="NVDA",
        stocktwits_score=0.7,
        stocktwits_confidence=0.8,
        gdelt_score=0.6,
        gdelt_confidence=0.7,
        technical_score=0.5,
        technical_confidence=0.6,
        fused_score=0.63,
        fused_confidence=0.72,
        direction="bullish",
        llm_explanation="All signals bullish.",
        signal_detail={},
    )
    session.add(opp)
    session.commit()
    opp_id = opp.id
    session.close()

    mock_order = {
        "alpaca_order_id": "order-123",
        "entry_price": 500.0,
        "qty": 1.0,
        "notional": 500.0,
        "stop_price": 485.0,
        "target_price": 525.0,
        "side": "buy",
        "ticker": "NVDA",
        "direction": "bullish",
    }
    with patch("app.trading.alpaca.submit_bracket_order", return_value=mock_order):
        resp = client.post(f"/trade/{opp_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["ticker"] == "NVDA"
    assert data["alpaca_order_id"] == "order-123"


def test_trade_already_traded(client):
    session = _TestSession()
    opp = session.query(Opportunity).filter_by(ticker="NVDA").first()
    assert opp is not None
    opp_id = opp.id
    session.close()

    with patch("app.trading.alpaca.submit_bracket_order", return_value={}):
        resp = client.post(f"/trade/{opp_id}")
    assert resp.status_code == 400
    assert "Already traded" in resp.json()["detail"]


def test_history_empty(client):
    resp = client.get("/history")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


def test_scan_endpoint(client):
    with patch("app.main.run_scan"):
        resp = client.get("/scan")
    assert resp.status_code == 200
    assert resp.json()["status"] == "scan complete"


def test_portfolio_alpaca_error(client):
    with patch("app.trading.alpaca.get_positions", side_effect=Exception("connection refused")):
        resp = client.get("/portfolio")
    assert resp.status_code == 502
