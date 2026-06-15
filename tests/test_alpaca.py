"""Alpaca order sizing tests."""
import os
from unittest.mock import patch

import pytest

os.environ.setdefault("ALPACA_API_KEY", "test")
os.environ.setdefault("ALPACA_SECRET_KEY", "test")

from app.trading import alpaca  # noqa: E402


class _Response:
    status_code = 200

    def raise_for_status(self):
        return None

    def json(self):
        return {"id": "order-123"}


def test_submit_bracket_order_scales_notional_by_confidence():
    with patch("app.trading.alpaca.get_account", return_value={"equity": "10000"}), \
         patch("app.trading.alpaca.get_positions", return_value=[]), \
         patch("app.trading.alpaca.get_latest_price", return_value=100.0), \
         patch("app.trading.alpaca.httpx.post", return_value=_Response()) as post:
        order = alpaca.submit_bracket_order("AAPL", "bullish", confidence=0.5)

    assert order["base_notional"] == 200.0
    assert order["notional"] == 100.0
    assert order["confidence"] == 0.5
    assert post.call_args.kwargs["json"]["qty"] == "1.0"


def test_submit_bracket_order_caps_notional_to_remaining_exposure():
    positions = [{"symbol": "MSFT", "market_value": "1950"}]
    with patch("app.trading.alpaca.get_account", return_value={"equity": "10000"}), \
         patch("app.trading.alpaca.get_positions", return_value=positions), \
         patch("app.trading.alpaca.get_latest_price", return_value=25.0), \
         patch("app.trading.alpaca.httpx.post", return_value=_Response()):
        order = alpaca.submit_bracket_order("AAPL", "bullish", confidence=1.0)

    assert order["notional"] == 50.0
    assert order["qty"] == 2.0


def test_submit_bracket_order_rejects_when_max_open_positions_reached():
    positions = [{"symbol": f"T{i}", "market_value": "100"} for i in range(5)]
    with patch("app.trading.alpaca.get_account", return_value={"equity": "10000"}), \
         patch("app.trading.alpaca.get_positions", return_value=positions):
        with pytest.raises(ValueError, match="Max open positions reached"):
            alpaca.submit_bracket_order("AAPL", "bullish", confidence=1.0)
