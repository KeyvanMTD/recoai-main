# app/db/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import get_settings
import certifi

settings = get_settings()
_client: AsyncIOMotorClient | None = None

def get_client() -> AsyncIOMotorClient:
    assert _client, "Mongo client not initialized"
    return _client

def get_db():
    return get_client()[settings.MONGO_DB]

async def connect():
    global _client
    _client = AsyncIOMotorClient(settings.MONGO_URI, 
                                 uuidRepresentation="standard", 
                                 tls=True,
                                 tlsCAFile=certifi.where())  # <- critical on some OS/containers)

async def disconnect():
    _client and _client.close()