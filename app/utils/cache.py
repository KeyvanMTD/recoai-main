import json
from redis.asyncio import Redis

async def cache_get(redis: Redis, key: str):
    if val := await redis.get(key):
        return json.loads(val)
    return None

async def cache_set(redis: Redis, key: str, value, ex: int = 60):
    await redis.set(key, json.dumps(value), ex=ex)

async def cache_delete(redis: Redis, key: str):
    await redis.delete(key)