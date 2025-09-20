# app/utils/locks.py
from __future__ import annotations
from typing import Optional
from redis.asyncio import Redis
import uuid, asyncio

class RedisLock:
    """
    Simple, single-instance lock using SET NX EX.
    Prevents multiple concurrent embeddings for the same key.
    """
    def __init__(self, redis: Redis, key: str, ttl: int = 20):
        self.redis = redis
        self.key = f"lock:{key}"
        self.ttl = ttl
        self._token: Optional[str] = None

    async def acquire(self) -> bool:
        token = uuid.uuid4().hex
        ok = await self.redis.set(self.key, token, nx=True, ex=self.ttl)
        if ok:
            self._token = token
            return True
        return False

    async def release(self) -> None:
        # best-effort: delete without token check (simple case)
        await self.redis.delete(self.key)

    async def wait(self, timeout: int = 10) -> None:
        """Wait for another worker to release the lock."""
        # poll quickly; for production you might use pubsub or backoff
        for _ in range(timeout * 10):
            if not await self.redis.exists(self.key):
                return
            await asyncio.sleep(0.1)
