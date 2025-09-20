# app/db/redis.py
import redis.asyncio as redis
from app.core.config import get_settings

settings = get_settings()
redis_client: redis.Redis | None = None


async def connect():
    """
    Essaie de connecter Redis si REDIS_URL est défini.
    Si non défini ou inaccessible, on log un warning mais on ne bloque pas l'app.
    """
    global redis_client
    if not settings.REDIS_URL:
        print("⚠️ No REDIS_URL configured, skipping Redis connection.")
        redis_client = None
        return

    try:
        print(f"Connecting to Redis at {settings.REDIS_URL}")
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        await redis_client.ping()
        print("✅ Redis connection successful")
    except Exception as e:
        print(f"⚠️ Failed to connect to Redis: {e}")
        redis_client = None  # fallback: désactive Redis


async def disconnect():
    """Ferme la connexion Redis si elle existe."""
    global redis_client
    if redis_client:
        await redis_client.aclose()
        redis_client = None
        print("ℹ️ Redis disconnected")


def get_redis() -> redis.Redis | None:
    """
    Getter Redis. Retourne None si Redis non configuré ou indisponible.
    À gérer côté appelant.
    """
    return redis_client
