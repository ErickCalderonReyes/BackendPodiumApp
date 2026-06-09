import redis.asyncio as aioredis
from config import settings

_redis_pool: aioredis.Redis | None = None


async def get_redis_pool() -> aioredis.Redis:
    global _redis_pool
    if _redis_pool is None:
        _redis_pool = await aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            ssl_cert_reqs=None,      # ← Azure Managed Redis requiere esto
        )
    return _redis_pool


async def get_redis() -> aioredis.Redis:
    return await get_redis_pool()