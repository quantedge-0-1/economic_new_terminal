import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.logger import get_logger
from app.db.session import init_db

logger = get_logger(__name__)

_filler_task: asyncio.Task | None = None


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _filler_task
    logger.info("Starting Economic News Terminal...")
    await init_db()
    _filler_task = asyncio.create_task(_memory_filler_loop())
    yield
    if _filler_task and not _filler_task.done():
        _filler_task.cancel()
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
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────
from app.api.v1.routes import (  # noqa: E402
    calendar, analysis, prices, surprise, news, alerts, sentiment,
)

app.include_router(calendar.router,  prefix="/api/v1/calendar",  tags=["Calendar"])
app.include_router(analysis.router,  prefix="/api/v1/analysis",  tags=["AI Analysis"])
app.include_router(prices.router,    prefix="/api/v1/prices",    tags=["Prices"])
app.include_router(surprise.router,  prefix="/api/v1/surprise",  tags=["Surprise"])
app.include_router(news.router,      prefix="/api/v1/news",      tags=["News"])
app.include_router(alerts.router,    prefix="/api/v1/alerts",    tags=["Alerts"])
app.include_router(sentiment.router, prefix="/api/v1/sentiment", tags=["Sentiment ISS"])


@app.get("/", tags=["Health"])
async def root():
    return {"status": "ok", "app": settings.app_name, "version": "1.0.0"}


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "healthy", "environment": settings.environment}
