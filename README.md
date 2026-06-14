# Stock Signal Trader

Autonomous signal aggregation + LLM reasoning + live paper trading.
Scans 20 liquid US stocks each morning, fuses 3 independent signals, and surfaces trade opportunities for human approval.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Daily Scan (09:00 EST)               │
├──────────────┬──────────────────┬───────────────────────────┤
│  Polymarket  │   GDELT News     │   yfinance Technical      │
│  Gamma API   │   Article Search │   RSI · MACD · MA cross   │
│  score ±1.0  │   LLM sentiment  │   score ±1.0              │
│  weight 0.40 │   weight 0.30    │   weight 0.30             │
└──────┬───────┴────────┬─────────┴────────────┬──────────────┘
       │                │                      │
       └────────────────▼──────────────────────┘
                  Weighted Fusion
              + Agreement Bonus (+0.15)
                        │
                   GPT-4o Synthesis
                (human-readable note)
                        │
             Confidence > 50% → Opportunity
                        │
              User clicks Trade ──► Alpaca
                                   Bracket Order
                                   SL -3% / TP +5%
```

## Signal Fusion

| Signal | Source | Weight |
|---|---|---|
| Polymarket | Market-implied probability on adjacent events | 0.40 |
| GDELT News | LLM sentiment on last 24h headlines | 0.30 |
| Technical | RSI(14) + MACD crossover + MA20/50 | 0.30 |

If all 3 signals agree in direction, confidence gets a **+0.15 bonus**.

## Stack

- **Backend**: FastAPI + SQLAlchemy + SQLite
- **Scheduler**: APScheduler (09:00 scan, 15:55 EOD close)
- **LLM**: OpenAI GPT-4o
- **Paper Trading**: Alpaca Markets
- **Frontend**: Vanilla HTML/CSS/JS (no framework)

## Setup

```bash
cp .env.example .env
# Fill in OPENAI_API_KEY, ALPACA_API_KEY, ALPACA_SECRET_KEY

pip install -r requirements.txt
uvicorn app.main:app --reload
```

Open http://localhost:8000

## Pages

- `/` — Opportunities: signal bars, confidence %, LLM explanation, Trade button
- `/portfolio.html` — Open positions: entry, current price, P&L
- `/history.html` — Closed trades: outcome, signal scores at entry

## API

```
GET  /opportunities          # Current opportunities
POST /trade/{id}             # Execute paper trade
GET  /portfolio              # Open positions (live from Alpaca)
GET  /history                # Closed trades
GET  /scan                   # Manual scan trigger
```

## Docker

```bash
docker compose up
```

## Tests

```bash
pip install -r requirements-dev.txt
pytest -v
```

## Position Sizing

- **Size**: 5% of portfolio equity per trade
- **Stop loss**: −3%
- **Take profit**: +5%
- **Time horizon**: daily (EOD close if stop/target not hit)
