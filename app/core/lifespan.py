from contextlib import asynccontextmanager
from fastapi import FastAPI
from app.db import mongo, redis as r
    
@asynccontextmanager
async def lifespan(app: FastAPI):
    
    # Startup
    await mongo.connect()
    await r.connect()

    yield

    # Shutdown
    await r.disconnect()
    await mongo.disconnect()