# app/core/lifespan.py
from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db import mongo, redis as r
from app.core.config import get_settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # --- Startup ---
    # Mongo obligatoire (si URI configurée)
    if settings.MONGO_URI:
        try:
            await mongo.connect()
            print("✅ Mongo connected")
        except Exception as e:
            print(f"❌ Mongo connection failed: {e}")
            raise
    else:
        print("⚠️ No MONGO_URI provided, skipping Mongo connection")

    # Redis optionnel
    if settings.REDIS_URL:
        try:
            await r.connect()
            print("✅ Redis connected")
        except Exception as e:
            print(f"⚠️ Redis connection failed (ignored): {e}")
    else:
        print("⚠️ No REDIS_URL provided, skipping Redis connection")

    # Application runs
    yield

    # --- Shutdown ---
    try:
        if settings.REDIS_URL:
            await r.disconnect()
            print("🔌 Redis disconnected")
    except Exception:
        pass

    try:
        if settings.MONGO_URI:
            await mongo.disconnect()
            print("🔌 Mongo disconnected")
    except Exception:
        pass
