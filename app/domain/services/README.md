# 📂 `services/` — Application & Domain Services

## 🎯 Purpose

Services encapsulate **business logic and orchestration**:

* Combine multiple **repositories** (MongoDB, external APIs, etc.).
* Apply **domain rules** (pricing, availability, permissions).
* Manage **caching**, **timeouts**, **retries**, **idempotency**.
* Interact with **providers** (OpenAI, etc.) in a controlled way.

> A service should **not** know about FastAPI/Starlette (`Request`, `HTTPException`, etc.).
> It raises **domain exceptions** or returns clear result objects.

---

## 📜 Principles

1. **Pure logic**: no web framework imports.
2. **Typed input/output** (Pydantic models or dataclasses).
3. **No direct DB access** → only via repositories.
4. **Observability** (metrics/logs) via injected adapters — no hard coupling.
5. **Deterministic behavior**: same input ⇒ same output (unless calling external services).

---

## 📐 Typical structure

```
services/
  product_svc.py     # product rules + caching
  ai_svc.py          # OpenAI integration (prompting, retries, timeouts)
  pricing_svc.py     # price & promotion calculations
  stock_svc.py       # stock orchestration (reservations, checks)
```

---

## 🧩 Minimal example (cache-aside + repo)

```python
# services/product_svc.py
from typing import Optional
from redis.asyncio import Redis
import json

from app.domain.repositories.product_repo import ProductRepo

CACHE_TTL = 60

class ProductService:
    def __init__(self, repo: ProductRepo, cache: Redis):
        self.repo = repo
        self.cache = cache

    async def get_by_id(self, pid: str) -> Optional[dict]:
        key = f"product:{pid}"
        if cached := await self.cache.get(key):
            return json.loads(cached)

        doc = await self.repo.get_by_id(pid)
        if doc:
            await self.cache.set(key, json.dumps(doc), ex=CACHE_TTL)
        return doc

    async def invalidate_cache(self, pid: str) -> None:
        await self.cache.delete(f"product:{pid}")
```

---

## 🤖 Example with OpenAI (timeouts, retries, cost control)

```python
# services/ai_svc.py
from typing import Optional
from openai import AsyncOpenAI, APIConnectionError, RateLimitError
import asyncio

DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3
BACKOFF_S = 1.5

class AISvc:
    def __init__(self, client: AsyncOpenAI):
        self.client = client

    async def summarize(self, text: str, model="gpt-4o-mini") -> str:
        last_err: Optional[Exception] = None
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                resp = await asyncio.wait_for(
                    self.client.chat.completions.create(
                        model=model,
                        messages=[{"role": "user", "content": f"Summarize: {text}"}],
                    ),
                    timeout=DEFAULT_TIMEOUT,
                )
                return (resp.choices[0].message.content or "").strip()
            except (APIConnectionError, RateLimitError, asyncio.TimeoutError) as e:
                last_err = e
                await asyncio.sleep(BACKOFF_S * attempt)
        raise RuntimeError(f"AI summarize failed after {MAX_RETRIES} retries") from last_err
```

---

## 🔒 Transactions, consistency & idempotency

* **MongoDB**: if updating multiple collections that impact state, consider **transactions** (sessions) in replica set clusters.
* **Idempotency**: for sensitive operations (payments, order creation), use an **idempotency key** (stored in Redis/Mongo) to avoid duplicates.
* **Cache invalidation**: a service that **writes** should **invalidate** relevant keys either *before* or *after* depending on your SLA (write-through vs cache-aside).

---

## 🎛️ Timeouts, retries & limits

* **Timeouts**: always set them here (DB calls, OpenAI, external HTTP).
* **Retries**: only on **transient errors** (network issues, 429, timeouts). **Never** retry on business rule errors (e.g., out of stock).
* **Rate limiting**: keep it here if it’s a business rule (per user/plan), otherwise handle it at the middleware level.

---

## 📊 Observability (without coupling)

* Inject a **logger** to trace inputs/outputs (mask secrets).
* Expose **counters** (calls, errors, cache hit/miss) via an injected metrics adapter (e.g., Prometheus).

---

## ✅ Testing (unit & integration)

* **Unit**: mock `ProductRepo`, `Redis`, `AsyncOpenAI`.
* **Contract tests**: cover *happy path*, *timeouts*, *retries*, *idempotency*, *cache hit/miss*.
* **Integration**: spin up Mongo/Redis containers (pytest + docker compose) if needed.

```python
# tests/services/test_product_svc.py
import pytest
import json
from services.product_svc import ProductService

class FakeRepo:
    async def get_by_id(self, pid): return {"_id": pid, "name": "X"}

class FakeRedis:
    def __init__(self): self.store = {}
    async def get(self,k): return self.store.get(k)
    async def set(self,k,v,ex=None): self.store[k]=v
    async def delete(self,k): self.store.pop(k, None)

@pytest.mark.asyncio
async def test_get_by_id_caches():
    svc = ProductService(FakeRepo(), FakeRedis())
    doc = await svc.get_by_id("42")
    assert doc["name"] == "X"
    # cache hit
    doc2 = await svc.get_by_id("42")
    assert doc2 == doc
```

---

## 🚫 Anti-patterns

* **Raising `HTTPException` here** → couples to web. Let the API layer map domain exceptions → HTTP.
* **Importing `fastapi`, `motor`, `starlette`** → breaks isolation.
* **Reimplementing DB logic** (complex aggregations) here → put them in a **repository**.

---

## 🔌 Typical injection into API

```python
# api/v2/routers/products.py
from fastapi import APIRouter, Depends, HTTPException
from app.api.deps import mongo_db, redis_dep
from app.domain.repositories.product_repo import ProductRepo
from app.domain.services.product_svc import ProductService

router = APIRouter()

@router.get("/products/{pid}")
async def get_product(pid: str, db=Depends(mongo_db), cache=Depends(redis_dep)):
    svc = ProductService(ProductRepo(db), cache)
    doc = await svc.get_by_id(pid)
    if not doc:
        raise HTTPException(404, "Product not found")
    return {"id": str(doc["_id"]), "name": doc["name"]}
```

---

## 🧭 Naming & organization

* One file per **business capability**: `product_svc.py`, `ai_svc.py`, `stock_svc.py`.
* Class vs pure functions:

  * **Class** if you inject multiple dependencies or maintain light state.
  * **Functions** if stateless and simple.

---

## 📝 Quick checklist

* [ ] No web/framework imports.
* [ ] Typed inputs/outputs, dedicated domain exceptions.
* [ ] Timeouts + retries (transient errors) + backoff.
* [ ] Clear cache strategy + invalidation.
* [ ] Idempotency key for sensitive operations.
* [ ] Logs/metrics via injected adapters.
* [ ] Unit tests (mocks) + targeted integration tests.

---
