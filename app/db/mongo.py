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
    """
    Create Motor client with explicit CA bundle.
    IMPORTANT: do not crash the app if the initial ping fails on Render.
    Keep a lazy client so requests can retry once Atlas/network is OK.
    """
    global _client, _db

    def _new_client() -> AsyncIOMotorClient:
        return AsyncIOMotorClient(
            settings.MONGO_URI,                 # e.g. mongodb+srv://.../...
            tls=True,                           # SRV implies TLS but keep explicit
            tlsCAFile=certifi.where(),          # critical on Render/containers
            uuidRepresentation="standard",
            serverSelectionTimeoutMS=6000,
            connectTimeoutMS=6000,
        )

    try:
        _client = _new_client()
        _db = _client[settings.MONGO_DB]
        # Soft fail-fast: try a ping, but don't abort on failure
        await _client.admin.command("ping")
        print("Mongo connected (ping ok)")
    except Exception as e:
        print(f"[WARN] Mongo ping at startup failed: {e}")
        try:
            # keep a lazy client; first real query will attempt to connect again
            _client = _new_client()
            _db = _client[settings.MONGO_DB]
            print("[WARN] Mongo will attempt lazy connection on first query")
        except Exception as e2:
            # as a last resort, keep None; routes that need DB will assert
            _client = None
            _db = None
            print(f"[ERROR] Mongo client init failed: {e2}")


async def disconnect():
    global _client, _db
    if _client:
        _client.close()
    _client = None
    _db = None
