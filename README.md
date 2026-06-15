# Stock Signal Trader

[![CI](https://github.com/ThomasKaragiannopoulos/stock-signal-trader/actions/workflows/ci.yml/badge.svg)](https://github.com/ThomasKaragiannopoulos/stock-signal-trader/actions/workflows/ci.yml)

Autonomous signal aggregation, NN-assisted prediction, and LLM-as-judge for live paper trading on 20 liquid US stocks.

## How it works

Each morning at 09:00 EST the scanner runs 6 phases:

```
Phase 1  Fetch StockTwits posts + GDELT news headlines (HTTP, no LLM)
Phase 2  LLM batch — score trader sentiment for all 20 tickers (1 call)
Phase 3  LLM batch — score news sentiment for all 20 tickers (1 call)
Phase 4  Technical indicators (RSI, MACD, MA20/50) + NN signal + weighted fusion
Phase 5  LLM batch — generate 2-sentence plain-English summary per opportunity (1 call)
Phase 6  LLM judge — sees all 4 signals + summary, outputs trade/skip + reason (1 call)
```

Total: **4 LLM calls** per full scan regardless of watchlist size.

## Signal architecture

```
┌─────────────────┬──────────────────┬─────────────────┬─────────────────┐
│   StockTwits    │   GDELT News     │   Technical     │   NN Model      │
│  Trader posts   │  Article Search  │  RSI·MACD·MA    │  sklearn MLP    │
│  LLM sentiment  │  LLM sentiment   │  rule-based     │  P(profit)      │
│  weight 0.30    │  weight 0.25     │  weight 0.25    │  weight 0.20    │
└────────┬────────┴────────┬─────────┴────────┬────────┴────────┬────────┘
         └─────────────────▼──────────────────▼─────────────────┘
                     Weighted fusion
              confidence = Σ(active_confs) / divisor
              divisor: 4→4.0  3→3.0  2→2.5  1→1.7
                           │
                    LLM as Judge
              trade / skip + 1-sentence reason
                           │
                 User reviews → Trade button
                           │
                    Alpaca paper order
          notional = equity × 2% × confidence
               bracket: SL −3% / TP +5%
```

## Confidence formula

Missing signals are penalised via the divisor rather than by zeroing weights — a single strong signal can still surface an opportunity, but always at a discount.

The NN contributes `confidence=0` until 10 closed trades exist, so it never pollutes results during the cold-start period.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + SQLAlchemy + SQLite |
| Scheduler | APScheduler (09:00 scan, 15:55 EOD close, 16:00 snapshot) |
| ML | scikit-learn MLPClassifier |
| LLM | OpenAI GPT-4o-mini |
| Paper trading | Alpaca Markets API |
| Frontend | Vanilla HTML/CSS/JS |

## Setup

```bash
cp .env.example .env
# Set OPENAI_API_KEY, ALPACA_API_KEY, ALPACA_SECRET_KEY

pip install -r requirements.txt
uvicorn app.main:app
```

Open **http://localhost:8000**

## Docker

```bash
docker compose up
```

## API

```
GET    /opportunities            # Latest scan results per ticker
GET    /opportunities/{id}       # Single opportunity + linked trade
POST   /trade/{id}               # Execute paper trade on Alpaca
GET    /portfolio                # Open positions (live from Alpaca)
GET    /history                  # Closed trades + realised P&L
GET    /snapshots                # Daily equity/cash snapshots (for equity curve)
GET    /scan?ticker=AAPL         # Trigger scan (all or single ticker)
GET    /scan/status              # Live phase progress
GET    /debug/{ticker}           # Raw signals for one ticker
GET    /watchlist                # Current watchlist [{ticker, company}]
POST   /watchlist                # Add ticker to watchlist
DELETE /watchlist/{ticker}       # Remove ticker from watchlist
```

## Frontend pages

- **Overview** (`/`) — live equity curve, open positions, last 5 closed trades
- **Today's Scan** (`/scan.html`) — signal cards per ticker with bars (StockTwits, GDELT, Technical, NN), confidence %, LLM summary, judge verdict (TRADE / SKIP)
- **History** (`/history.html`) — full closed-trade table with analytics: win rate, total P&L, avg per trade, cumulative P&L chart
- **Settings** (`/settings.html`) — editable watchlist; changes take effect on next scan
- **Detail** (`/detail.html?id=`) — drilldown per opportunity: all signal panels, raw data, trade execution, P&L if closed

## Tests

```bash
pip install ruff pytest
ruff check app/ tests/
pytest tests/ -v
```

## Position sizing

Notional is scaled by signal confidence before the order is placed:

```
base_notional = equity × POSITION_SIZE_PCT          # default 2%
notional      = min(base_notional × confidence, remaining_exposure)
```

A confidence of 0.5 halves the position; 1.0 uses the full base allocation.
Remaining exposure = `MAX_TOTAL_EXPOSURE_PCT` (20%) minus current open exposure.

| Parameter | Default | Env var |
|---|---|---|
| Base allocation | 2% of equity | `POSITION_SIZE_PCT` |
| Max open positions | 5 | `MAX_OPEN_POSITIONS` |
| Max total exposure | 20% of equity | `MAX_TOTAL_EXPOSURE_PCT` |
| Stop loss | −3% | `STOP_LOSS_PCT` |
| Take profit | +5% | `TAKE_PROFIT_PCT` |

**Time horizon**: daily — EOD close at 15:55 EST if stop/target not hit by market close.
