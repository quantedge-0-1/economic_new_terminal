import asyncio
import json
from contextlib import asynccontextmanager
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logger import get_logger
from app.db.session import init_db

# ── WebSocket connection manager ──────────────────────────────────────────────
class _WSManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        self.active.discard(ws)

    async def broadcast(self, data: dict):
        msg  = json.dumps(data)
        dead = set()
        for ws in self.active:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        self.active -= dead

ws_manager = _WSManager()
_last_broadcast_event_id: str | None = None

logger = get_logger(__name__)

_filler_task:   asyncio.Task | None = None
_calendar_task: asyncio.Task | None = None
_price_task:    asyncio.Task | None = None


async def _memory_filler_loop() -> None:
    """Background task: fill pending EventMemory rows with Polygon price data every 10 min."""
    from app.db.session import db_session
    from app.services.sentiment.memory import fill_pending_moves

    await asyncio.sleep(30)  # Initial delay — let the server fully start
    while True:
        try:
            async with db_session() as db:
                updated = await fill_pending_moves(db)
                if updated:
                    logger.info("[MemoryFiller] filled %d rows", updated)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[MemoryFiller] error: %s", exc)
        await asyncio.sleep(600)  # Run every 10 minutes


async def _price_poller_loop() -> None:
    """
    Keep _price_history buffer alive regardless of whether the frontend is open.
    Runs every 45s — matches prices_cache_ttl so each iteration fetches fresh data.
    Without this, PreRelease scanner and ISS/MCS go stale when the browser is closed.
    """
    from app.services.prices.engine import get_all_prices
    from app.services.prices.history import record_prices

    await asyncio.sleep(10)
    while True:
        try:
            prices = await get_all_prices()
            record_prices(prices)
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[PricePoller] error: %s", exc)
        await asyncio.sleep(45)


async def _ws_broadcast_loop() -> None:
    """
    Poll for new high-impact releases every 30s and broadcast to WebSocket clients.
    Sends { type: 'release', event: {...} } when a new event appears.
    """
    global _last_broadcast_event_id
    from datetime import UTC, datetime, timedelta

    await asyncio.sleep(20)
    while True:
        try:
            if ws_manager.active:
                from app.db.session import db_session
                from app.db.models import EconomicEvent
                from sqlalchemy import and_, or_, select

                now   = datetime.now(UTC)
                since = now - timedelta(hours=1)

                async with db_session() as db:
                    row = (await db.execute(
                        select(EconomicEvent)
                        .where(
                            and_(
                                EconomicEvent.event_at  >= since,
                                EconomicEvent.event_at  <= now,
                                EconomicEvent.actual.isnot(None),
                                or_(
                                    EconomicEvent.is_high_impact == True,
                                    EconomicEvent.importance     == "high",
                                ),
                            )
                        )
                        .order_by(EconomicEvent.event_at.desc())
                        .limit(1)
                    )).scalar_one_or_none()

                    if row is not None:
                        event_key = f"{row.event_name}:{row.event_at}"
                        if event_key != _last_broadcast_event_id:
                            _last_broadcast_event_id = event_key
                            surprise_pct = None
                            if row.actual and row.forecast and row.forecast != 0:
                                surprise_pct = round(
                                    (row.actual - row.forecast) / abs(row.forecast) * 100, 1
                                )
                            await ws_manager.broadcast({
                                "type": "release",
                                "event": {
                                    "event_name":   row.event_name,
                                    "currency":     row.currency,
                                    "actual":       row.actual,
                                    "forecast":     row.forecast,
                                    "previous":     row.previous,
                                    "unit":         row.unit,
                                    "surprise_pct": surprise_pct,
                                    "event_at":     row.event_at.isoformat(),
                                },
                            })
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[WSBroadcast] error: %s", exc)
        await asyncio.sleep(30)


async def _calendar_refresh_loop() -> None:
    """
    Background task: auto-refresh calendar from FRED + scraper every 5 minutes.
    Critical for picking up actuals automatically when economic data is released.
    """
    from app.db.session import db_session
    from app.services.calendar.engine import CalendarEngine

    engine = CalendarEngine()
    await asyncio.sleep(15)  # Wait for DB init before first run
    while True:
        try:
            async with db_session() as db:
                result = await engine.refresh(db)
                logger.info(
                    "[CalendarRefresh] inserted=%d updated=%d skipped=%d",
                    result["inserted"], result["updated"], result["skipped"],
                )
        except asyncio.CancelledError:
            break
        except Exception as exc:
            logger.warning("[CalendarRefresh] error: %s", exc)
        await asyncio.sleep(300)  # Every 5 minutes


_ws_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _filler_task, _calendar_task, _price_task, _ws_task
    logger.info("Starting Economic News Terminal...")
    await init_db()
    _filler_task   = asyncio.create_task(_memory_filler_loop())
    _calendar_task = asyncio.create_task(_calendar_refresh_loop())
    _price_task    = asyncio.create_task(_price_poller_loop())
    _ws_task       = asyncio.create_task(_ws_broadcast_loop())
    yield
    for task in (_filler_task, _calendar_task, _price_task, _ws_task):
        if task and not task.done():
            task.cancel()
    logger.info("Shutdown complete")


app = FastAPI(
    title="Economic News Terminal",
    version="1.0.0",
    description="Institutional macro intelligence terminal — Smart Money grade",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "https://tradingagenda.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
from app.api.v1.routes import (  # noqa: E402
    calendar, analysis, prices, surprise, news, alerts, sentiment, pre_release, market,
)

app.include_router(calendar.router,    prefix="/api/v1/calendar",     tags=["Calendar"])
app.include_router(analysis.router,    prefix="/api/v1/analysis",     tags=["AI Analysis"])
app.include_router(prices.router,      prefix="/api/v1/prices",       tags=["Prices"])
app.include_router(surprise.router,    prefix="/api/v1/surprise",     tags=["Surprise"])
app.include_router(news.router,        prefix="/api/v1/news",         tags=["News"])
app.include_router(alerts.router,      prefix="/api/v1/alerts",       tags=["Alerts"])
app.include_router(sentiment.router,   prefix="/api/v1/sentiment",    tags=["Sentiment ISS"])
app.include_router(pre_release.router, prefix="/api/v1/pre-release",  tags=["Pre-Release"])
app.include_router(market.router,      prefix="/api/v1/market",       tags=["Market"])


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "app": settings.app_name, "version": "1.0.0"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy", "environment": settings.environment}


@app.websocket("/ws/terminal")
async def ws_terminal(websocket: WebSocket):
    """
    WebSocket endpoint for the PWA mobile companion.
    Broadcasts { type: 'release', event: {...} } when a new high-impact event
    is released. The PWA subscribes and vibrates/shows a modal on receipt.
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            # Keep the connection alive — client sends pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
