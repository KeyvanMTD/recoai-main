from typing import Optional, Iterable
from app.domain.models.product import RecoItem
import hashlib
import json

def _h(filters, model, limit):
    """
    Create a short hash based on filters, model, and limit.
    Used to generate unique cache keys for different query parameters.
    """
    s = json.dumps({"f": filters or {}, "m": model, "k": limit}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha1(s.encode()).hexdigest()[:10]

class RecoProductsCacheRepo:
    """
    Adapter for caching recommandations products in Redis (or any cache backend).
    Stores and retrieves lists of RecoItem objects.
    """
    def __init__(self, redis, key_prefix: str):
        """
        Initialize the cache repository with a Redis client and a key prefix.
        
        Args:
            redis: Redis client instance
            key_prefix: Prefix for cache keys (e.g., 'sim' or 'comp')
        """
        self.cache = redis  # Use the passed Redis instance
        self.prefix = key_prefix

    def key(self, version: str, product_id: str, limit: int, filt, model: str) -> str:
        """
        Build a unique cache key for a given query.
        Combines API version, prefix, product ID, and a hash of filters/model/limit.
        """
        return f"{version}:{self.prefix}:{product_id}:{_h(filt, model, limit)}"

    async def get(self, key: str) -> Optional[list[RecoItem]]:
        """
        Retrieve a list of RecoItem from cache by key.
        Returns None if not found.
        """
        raw = await self.cache.get(key)
        if raw:
            data = json.loads(raw)
            # Validate and convert each cached dict to a RecoItem instance
            return [RecoItem.model_validate(x) for x in data]
        return None

    async def set(self, key: str, items: Iterable[RecoItem], ttl: int) -> None:
        """
        Store a list of RecoItem in cache under the given key.
        Serializes items to JSON and sets a TTL (expiration).
        """
        payload = [i.model_dump() for i in items]
        await self.cache.set(key, json.dumps(payload), ex=ttl)