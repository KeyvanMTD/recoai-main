# 📂 `db/` — Database & Cache Clients

## 🎯 Purpose

The **`db/`** folder contains **infrastructure code** for connecting to and managing:

* **MongoDB** (via `motor`)
* **Redis** (via `redis.asyncio`)

It is responsible for:

* Initializing and closing database/cache connections.
* Providing **dependency-injection friendly** access to DB clients.
* Keeping all connection logic **isolated from the domain layer**.

---

## 📜 Principles

1. **One responsibility** → just connection handling, no business logic.
2. **Async-first** → all DB and cache clients are asynchronous to match FastAPI’s async I/O model.
3. **Lifecycle-aware** → connections open at app startup, close at shutdown (via `lifespan` or startup/shutdown events).
4. **Configuration-driven** → all settings (URIs, ports, DB names) come from `core/config.py` or environment variables.

---

## 📐 Typical structure

```
db/
  mongo.py       # MongoDB connection handling
  redis.py       # Redis connection handling
```

---

## 🧩 Example: `mongo.py`

```python
# db/mongo.py
from motor.motor_asyncio import AsyncIOMotorClient
from app.core.config import settings

_client: AsyncIOMotorClient | None = None

def get_client() -> AsyncIOMotorClient:
    """Return the global MongoDB client instance."""
    assert _client, "Mongo client not initialized"
    return _client

def get_db():
    """Return the configured MongoDB database."""
    return get_client()[settings.mongo_db]

async def connect():
    """Open a MongoDB connection."""
    global _client
    _client = AsyncIOMotorClient(settings.mongo_uri, uuidRepresentation="standard")

async def disconnect():
    """Close the MongoDB connection."""
    if _client:
        _client.close()
```

---

## 🧩 Example: `redis.py`

```python
# db/redis.py
import redis.asyncio as redis
from app.core.config import settings

redis_client: redis.Redis | None = None

async def connect():
    """Open a Redis connection."""
    global redis_client
    redis_client = redis.from_url(settings.redis_url, decode_responses=True)

async def disconnect():
    """Close the Redis connection."""
    if redis_client:
        await redis_client.aclose()
```

---

## 🔄 Typical usage with FastAPI lifespan

```python
# main.py
from fastapi import FastAPI
from contextlib import asynccontextmanager
from app.db import mongo, redis as r

@asynccontextmanager
async def lifespan(app: FastAPI):
    await mongo.connect()
    await r.connect()
    yield
    await r.disconnect()
    await mongo.disconnect()

app = FastAPI(lifespan=lifespan)
```

---

## ✅ Best practices

* Keep **all** DB/cache initialization here — never in routers or services.
* Use **dependency injection** (`Depends`) to pass DB instances into repositories.
* Close connections gracefully on shutdown to avoid leaks.
* Never hardcode connection strings → load them from `core/config.py`.

---

## 🚫 Anti-patterns

* **Connecting inside a request handler** → creates a new connection for every request and kills performance.
* **Embedding queries here** → belongs to repositories.
* **Mixing business logic with connection code** → violates separation of concerns.

---

## 📎 Useful references

* [Motor (Async MongoDB)](https://motor.readthedocs.io/)
* [redis-py asyncio](https://redis-py.readthedocs.io/en/stable/examples/asyncio_examples.html)
* [FastAPI Lifespan Events](https://fastapi.tiangolo.com/advanced/events/)

---

💡 **Tip**:
If you add more infrastructure (e.g., PostgreSQL, Elasticsearch), keep the same pattern: one file per connection type, lifecycle methods (`connect`, `disconnect`), and a clean dependency provider (`get_client`, `get_db`, etc.).

---
