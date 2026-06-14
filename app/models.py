from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, create_engine, text
from sqlalchemy.orm import declarative_base, sessionmaker

Base = declarative_base()


class Opportunity(Base):
    __tablename__ = "opportunities"

    id = Column(Integer, primary_key=True)
    ticker = Column(String, nullable=False)
    scanned_at = Column(DateTime, default=datetime.utcnow)

    stocktwits_score = Column(Float)
    stocktwits_confidence = Column(Float)
    gdelt_score = Column(Float)
    gdelt_confidence = Column(Float)
    technical_score = Column(Float)
    technical_confidence = Column(Float)

    fused_score = Column(Float)
    fused_confidence = Column(Float)
    direction = Column(String)  # "bullish" | "bearish" | "neutral"

    nn_score = Column(Float, default=0.0)
    nn_confidence = Column(Float, default=0.0)

    llm_explanation = Column(String)
    judge_verdict = Column(String)   # "trade" | "skip"
    judge_reason = Column(String)
    signal_detail = Column(JSON)  # raw detail from each signal

    traded = Column(Integer, default=0)  # 0 = not traded, 1 = traded


class Trade(Base):
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True)
    opportunity_id = Column(Integer)
    ticker = Column(String, nullable=False)
    direction = Column(String)
    executed_at = Column(DateTime, default=datetime.utcnow)

    entry_price = Column(Float)
    qty = Column(Float)
    notional = Column(Float)

    stop_price = Column(Float)
    target_price = Column(Float)

    alpaca_order_id = Column(String)
    status = Column(String, default="open")  # "open" | "closed"
    exit_price = Column(Float)
    realised_pnl = Column(Float)
    closed_at = Column(DateTime)

    signal_scores = Column(JSON)


def get_engine(db_url: str = "sqlite:///./trader.db"):
    engine = create_engine(db_url, connect_args={"check_same_thread": False})
    _migrate(engine)
    return engine


def _migrate(engine) -> None:
    """Add new columns to existing tables without dropping data."""
    new_cols = [
        ("opportunities", "stocktwits_score", "FLOAT DEFAULT 0"),
        ("opportunities", "stocktwits_confidence", "FLOAT DEFAULT 0"),
        ("opportunities", "nn_score", "FLOAT DEFAULT 0"),
        ("opportunities", "nn_confidence", "FLOAT DEFAULT 0"),
        ("opportunities", "judge_verdict", "VARCHAR"),
        ("opportunities", "judge_reason", "TEXT"),
    ]
    with engine.connect() as conn:
        for table, col, col_def in new_cols:
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col} {col_def}"))
                conn.commit()
            except Exception:
                pass  # column already exists


def get_session_factory(engine):
    return sessionmaker(bind=engine)
