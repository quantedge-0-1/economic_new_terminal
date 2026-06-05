"""
Redis client — async, singleton.
Used only for caching API responses and Celery broker.
"""

from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import settings
from app.core.logger import get_logger

logger = get_logger(__name__)

_redis: aioredis.Redis | None = None


async def get_redis() -> aioredis.Redis | None:
    global _redis
    if _redis is not None:
        return _redis
    try:
        client = aioredis.from_url(settings.redis_url, decode_responses=True)
        await client.ping()
        _redis = client
        return _redis
    except Exception as exc:
        logger.warning(f"Redis unavailable: {exc}")
        return None


async def close_redis() -> None:
    global _redis
    if _redis is not None:
        await _redis.aclose()
        _redis = None
