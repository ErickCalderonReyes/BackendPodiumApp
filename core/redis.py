import redis.asyncio as aioredis
from config import settings

# Pool compartido — una sola conexión para toda la app
_redis_pool: aioredis.Redis | None = None


async def get_redis_pool() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_pool


async def get_redis() -> aioredis.Redis:
    """Dependencia FastAPI — inyecta el cliente Redis en los routers."""
    return await get_redis_pool()