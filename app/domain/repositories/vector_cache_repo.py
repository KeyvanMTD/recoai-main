# app/domain/repositories/vector_cache_repo.py
from __future__ import annotations
from typing import Optional, Sequence, Any
from redis.asyncio import Redis
import json, hashlib

"""
Note: 
    - This repository is an adapter for storing and retrieving product embeddings (vectors) in Redis.
    - No business logic here—just cache access (get/set/invalidate).
    - Do not store vectors in Redis directly; use MongoDB Atlas for that.
"""

def _stable_hash(model: str) -> str:
    """
    Generate a short, stable hash for the model string.
    Useful for cache key versioning when model or prompt changes.
    """
    return hashlib.sha1(model.encode("utf-8")).hexdigest()[:8]

class VectorCacheRepo:
    """
    Adapter for storing and retrieving product embeddings (vectors) in Redis.
    No business logic here—just cache access (get/set/invalidate).
    """
    def __init__(self, redis: Redis, prefix: str = "vec"):
        # Redis client instance and cache key prefix
        self.redis = redis
        self.prefix = prefix

    def key(self, product_id: str, model: str) -> str:
        """
        Build a unique cache key for a product's vector, based on product_id and model.
        """
        return f"{self.prefix}:{_stable_hash(model)}:{product_id}"

    async def get(self, key: str) -> Optional[list[float]]:
        """
        Retrieve the embedding vector from Redis by key.
        Returns None if not found.
        Embeddings can be large; JSON is used for serialization.
        """
        if raw := await self.redis.get(key):
            return json.loads(raw)
        return None

    async def set(self, key: str, vector: Sequence[float], ttl: int) -> None:
        """
        Store the embedding vector in Redis under the given key.
        Serializes the vector to JSON and sets a TTL (expiration).
        """
        await self.redis.set(key, json.dumps(list(vector), separators=(",", ":")), ex=ttl)

    async def invalidate(self, product_id: str, model: str) -> int:
        """
        Remove the cached vector for a specific product and model.
        Returns the number of keys deleted (0 or 1).
        """
        k = self.key(product_id, model)
        return await self.redis.delete(k)
