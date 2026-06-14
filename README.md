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
               bracket: SL −3% / TP +5%
```

## Confidence formula

Missing signals are penalised via the divisor rather than by zeroing weights — a single strong signal can still surface an opportunity, but always at a discount.

The NN contributes `confidence=0` until 10 closed trades exist, so it never pollutes results during the cold-start period.

## Stack

| Layer | Technology |
|---|---|
| Backend | FastAPI + SQLAlchemy + SQLite |
| Scheduler | APScheduler (09:00 scan, 15:55 EOD close) |
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
GET  /opportunities          # Latest scan results per ticker
POST /trade/{id}             # Execute paper trade on Alpaca
GET  /portfolio              # Open positions (live from Alpaca)
GET  /history                # Closed trades + realised P&L
GET  /scan?ticker=AAPL       # Trigger scan (all or single ticker)
GET  /scan/status            # Live phase progress
GET  /debug/{ticker}         # Raw signals for one ticker
```

## Frontend pages

- **Opportunities** — signal bars (StockTwits, GDELT, Technical, NN), confidence %, 2-sentence LLM summary, judge verdict (TRADE / SKIP), expandable raw data panel
- **Portfolio** — open positions, entry price, current price, unrealised P&L
- **History** — closed trades, realised P&L, signal scores at entry

## Tests

```bash
pip install ruff pytest
ruff check app/ tests/
pytest tests/ -v
```

## Position sizing

- **Per trade**: 5% of portfolio equity
- **Stop loss**: −3%
- **Take profit**: +5%
- **Time horizon**: daily (EOD close if stop/target not hit)
