# app/api/deps.py
from fastapi import Depends
from app.db.mongo import get_db
from app.db.redis import get_redis

# Dependency for injecting the MongoDB database into endpoints/services
async def mongo_db(db = Depends(get_db)):
    # Returns the MongoDB database instance (async)
    return db

# Dependency for injecting the Redis client into endpoints/services
def redis_dep():
    return get_redis()