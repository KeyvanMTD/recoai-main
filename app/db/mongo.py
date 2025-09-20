# app/db/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from app.core.config import get_settings
import certifi

settings = get_settings()

_client: AsyncIOMotorClient | None = None
_db: AsyncIOMotorDatabase | None = None


def get_client() -> AsyncIOMotorClient:
    assert _client is not None, "Mongo client not initialized"
    return _client


def get_db() -> AsyncIOMotorDatabase:
    assert _db is not None, "Mongo DB not initialized"
    return _db


async def connect():
    """Create Motor client with explicit CA bundle (Render/containers need this)."""
    global _client, _db
    _client = AsyncIOMotorClient(
        settings.MONGO_URI,
        tls=True,
        tlsCAFile=certifi.where(),          # <- important for Atlas on Render
        uuidRepresentation="standard",
        serverSelectionTimeoutMS=8000,
        connectTimeoutMS=8000,
    )
    _db = _client[settings.MONGO_DB]
    # Fail fast if bad network/cert
    await _client.admin.command("ping")
    print("Mongo connected")


async def disconnect():
    global _client, _db
    if _client:
        _client.close()
    _client = None
    _db = None
