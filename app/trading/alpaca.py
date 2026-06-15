"""
Alpaca paper trading: execute bracket orders, fetch positions, sync trade status.
"""
import os

import httpx

ALPACA_BASE = "https://paper-api.alpaca.markets/v2"
POSITION_SIZE_PCT = float(os.getenv("POSITION_SIZE_PCT", "0.02"))
MAX_OPEN_POSITIONS = int(os.getenv("MAX_OPEN_POSITIONS", "5"))
MAX_TOTAL_EXPOSURE_PCT = float(os.getenv("MAX_TOTAL_EXPOSURE_PCT", "0.20"))
STOP_LOSS_PCT     = float(os.getenv("STOP_LOSS_PCT", "0.03"))
TAKE_PROFIT_PCT   = float(os.getenv("TAKE_PROFIT_PCT", "0.05"))


def _headers() -> dict:
    return {
        "APCA-API-KEY-ID": os.environ["ALPACA_API_KEY"],
        "APCA-API-SECRET-KEY": os.environ["ALPACA_SECRET_KEY"],
        "Content-Type": "application/json",
    }


def get_account() -> dict:
    resp = httpx.get(f"{ALPACA_BASE}/account", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_positions() -> list[dict]:
    resp = httpx.get(f"{ALPACA_BASE}/positions", headers=_headers(), timeout=10)
    resp.raise_for_status()
    return resp.json()


def get_position(ticker: str) -> dict | None:
    resp = httpx.get(f"{ALPACA_BASE}/positions/{ticker}", headers=_headers(), timeout=10)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.json()


def get_latest_price(ticker: str) -> float:
    resp = httpx.get(
        f"https://data.alpaca.markets/v2/stocks/{ticker}/trades/latest",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return float(resp.json()["trade"]["p"])


def submit_bracket_order(ticker: str, direction: str, confidence: float = 1.0) -> dict:
    """
    Places a market bracket order. Direction: "bullish" → buy, "bearish" → sell.
    Position is sized from base equity allocation, scaled by signal confidence.
    """
    account = get_account()
    equity = float(account["equity"])
    positions = get_positions()
    _check_risk_limits(positions, equity, ticker)

    confidence = max(0.0, min(1.0, float(confidence or 0.0)))
    base_notional = equity * POSITION_SIZE_PCT
    remaining_exposure = max(0.0, equity * MAX_TOTAL_EXPOSURE_PCT - _current_exposure(positions))
    notional = round(min(base_notional * confidence, remaining_exposure), 2)
    if notional <= 0:
        raise ValueError("Position size is zero after confidence scaling and exposure limits")

    price = get_latest_price(ticker)
    qty = round(notional / price, 4)
    if qty <= 0:
        raise ValueError("Quantity is zero after position sizing")

    side = "buy" if direction == "bullish" else "sell"
    stop_price = round(price * (1 - STOP_LOSS_PCT) if side == "buy" else price * (1 + STOP_LOSS_PCT), 4)
    take_profit_price = round(price * (1 + TAKE_PROFIT_PCT) if side == "buy" else price * (1 - TAKE_PROFIT_PCT), 4)

    order_payload = {
        "symbol": ticker,
        "qty": str(qty),
        "side": side,
        "type": "market",
        "time_in_force": "day",
        "order_class": "bracket",
        "stop_loss": {"stop_price": str(stop_price)},
        "take_profit": {"limit_price": str(take_profit_price)},
    }

    resp = httpx.post(f"{ALPACA_BASE}/orders", headers=_headers(), json=order_payload, timeout=15)
    resp.raise_for_status()
    order = resp.json()
    if not order.get("id"):
        raise ValueError(f"Alpaca returned malformed order response: {order!r}")

    return {
        "alpaca_order_id": order["id"],
        "entry_price": price,
        "qty": qty,
        "notional": notional,
        "confidence": confidence,
        "base_notional": round(base_notional, 2),
        "stop_price": stop_price,
        "target_price": take_profit_price,
        "side": side,
    }


def _check_risk_limits(positions: list[dict], equity: float, ticker: str) -> None:
    if any(p.get("symbol") == ticker for p in positions):
        raise ValueError(f"Already have an open position in {ticker}")
    if len(positions) >= MAX_OPEN_POSITIONS:
        raise ValueError(f"Max open positions reached ({MAX_OPEN_POSITIONS})")
    if _current_exposure(positions) >= equity * MAX_TOTAL_EXPOSURE_PCT:
        raise ValueError(f"Max total exposure reached ({MAX_TOTAL_EXPOSURE_PCT:.0%})")


def _current_exposure(positions: list[dict]) -> float:
    exposure = 0.0
    for position in positions:
        try:
            exposure += abs(float(position.get("market_value", 0.0)))
        except (TypeError, ValueError):
            continue
    return exposure


def get_order(order_id: str, nested: bool = False) -> dict:
    params = {"nested": "true"} if nested else None
    resp = httpx.get(f"{ALPACA_BASE}/orders/{order_id}", headers=_headers(), params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()


def close_all_eod() -> list[dict]:
    """Close all open positions (called at end of day)."""
    resp = httpx.delete(f"{ALPACA_BASE}/positions", headers=_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()
