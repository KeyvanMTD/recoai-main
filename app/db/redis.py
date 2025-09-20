# app/db/redis.py
import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()
redis_client: redis.Redis | None = None

async def connect():
    global redis_client
    try:
        print(f"Connecting to Redis at {settings.REDIS_URL}")
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis_client.ping()
        print("Redis connection successful")
    except Exception as e:
        print(f"Failed to connect to Redis: {e}")
        raise

async def disconnect():
    if redis_client:
        await redis_client.aclose()

# Add a getter function
def get_redis():
    assert redis_client is not None, "Redis not initialized"
    return redis_client