# Economic News Terminal

Real-time institutional-grade economic news terminal for XAUUSD traders. Combines live macro calendar data, AI analysis (Claude), and Smart Money price structure signals into a single dashboard.

## Features

- **Economic Calendar** — live events with actual/forecast/previous values and surprise %
- **AI Analysis** — 4-line institutional analysis (SEÑAL / SCORES / PRECIO / ACCIÓN) via Claude
- **ISS (Institutional Sentiment Score)** — NSS (Claude Haiku) + MCS (live price confirmation)
- **Pre-Release Signals** — BSL/SSL/EQ levels and bias 10 min before high-impact releases
- **Price History** — real-time XAUUSD, DXY, US10Y, VIX via Twelve Data / Polygon
- **News Flash** — breaking macro news with AI triage

## Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI (async), SQLite + WAL, aiosqlite |
| AI | Claude Opus (analysis), Claude Haiku (sentiment/pre-release) |
| Data | FRED API, Twelve Data, Polygon.io |
| Frontend | React 18, Vite, Tailwind CSS |

## Prerequisites

- Python 3.11+
- Node.js 18+
- API keys for: FRED, Twelve Data, Polygon, Anthropic

## Setup

### 1. Clone and configure environment

```bash
git clone <repo-url>
cd economic_news_terminal

# Create backend env file from template
cp .env.example backend/.env
# Edit backend/.env and fill in your API keys
```

### 2. Backend

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

### 3. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

## API Keys

| Key | Free Tier | Where to get |
|-----|-----------|-------------|
| `FRED_API_KEY` | Yes | [fred.stlouisfed.org](https://fred.stlouisfed.org/docs/api/api_key.html) |
| `TWELVE_DATA_API_KEY` | 8 calls/min | [twelvedata.com](https://twelvedata.com) |
| `POLYGON_API_KEY` | Yes | [polygon.io](https://polygon.io) |
| `ANTHROPIC_API_KEY` | Pay-per-use | [console.anthropic.com](https://console.anthropic.com) |

## Architecture

```
backend/
  app/
    api/v1/routes/     # FastAPI route handlers
    core/              # Config, cache, logger, Claude retry
    db/                # SQLite models and session
    services/
      ai/              # Individual event analysis (Claude Opus)
      consolidated_analysis_service.py  # Multi-event analysis
      pre_release/     # Pre-release BSL/SSL signals + AI (Haiku)
      sentiment/       # ISS = NSS (Haiku) + MCS (price confirmation)
      calendar/        # FRED + investing.com scraper
      prices/          # Real-time price history buffer
      news/            # RSS + GDELT news feeds
      alerts/          # Divergence and signal alerts
    main.py            # Background tasks: price poller, calendar refresh
frontend/
  src/
    components/        # Panel components (Calendar, AI Analysis, ISS, etc.)
    hooks/             # Data fetching hooks
```

## ISS Formula

```
ISS = NSS × 0.6 + MCS × 0.4

NSS: Claude Haiku classifies event impact on Gold (0-100)
MCS: Price confirmation across 1m/5m/15m/30m windows (0-100)

85-100 → EXTREME BULLISH
70-84  → BULLISH
55-69  → MODERATELY BULLISH
45-54  → NEUTRAL
30-44  → BEARISH
0-29   → EXTREME BEARISH
```

## Notes

- Claude API calls use exponential backoff retry (2s / 4s / 8s) on 529 overload errors
- Analysis responses are cached in-memory: 10 min for individual, 5 min for consolidated/pre-release
- Only successful Claude responses (tokens_used > 0) are written to cache
- SQLite runs in WAL mode for concurrent reads during background tasks
