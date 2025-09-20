# 📂 `api/` — API Layer (Versioned Routers & Dependencies)

## 🎯 Purpose

The **`api/`** folder contains:

* **Routers** (HTTP endpoints, grouped by domain and API version)
* **Schemas** specific to each API version
* **Dependency injection** logic (`deps.py`) for services, repositories, DB clients, and caches

This is the **only layer that knows about FastAPI** and HTTP details (status codes, request/response objects, exceptions).

---

## 📜 Principles

1. **Versioning first**: Keep each API version isolated in its own subfolder (`v1/`, `v2/`).
2. **Stateless**: Routers should not hold any state between requests.
3. **Thin controllers**: Routers handle HTTP, but delegate business logic to services.
4. **Schema isolation**: If a model changes between versions, define separate Pydantic schemas per version.

---

## 📐 Typical structure

```
api/
  deps.py                  # Shared dependencies (DI)
  v1/
    routers/
      health.py
      products.py
      ai.py
    schemas/
      product.py
  v2/
    routers/
      products.py
    schemas/
      product.py
```

---

## 🧩 Example: `deps.py`

```python
# api/deps.py
from fastapi import Depends
from app.db.mongo import get_db
from app.db.redis import redis_client

async def mongo_db(db=Depends(get_db)):
    return db

def redis_dep():
    assert redis_client, "Redis not initialized"
    return redis_client
```

---

## 🧩 Example: Versioned Router

```python
# api/v1/routers/products.py
from fastapi import APIRouter, Depends, HTTPException
from app.api.deps import mongo_db, redis_dep
from app.domain.repositories.product_repo import ProductRepo
from app.domain.services.product_svc import ProductService
from app.api.v1.schemas.product import ProductOut

router = APIRouter()

@router.get("/products/{pid}", response_model=ProductOut)
async def get_product(pid: str, db=Depends(mongo_db), cache=Depends(redis_dep)):
    svc = ProductService(ProductRepo(db), cache)
    doc = await svc.get_by_id(pid)
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return doc
```

---

## 🧩 Example: Versioned Schema

```python
# api/v1/schemas/product.py
from pydantic import BaseModel

class ProductOut(BaseModel):
    id: str
    name: str
    price: float
```

---

## 🔄 Request flow

```
HTTP Request
   ↓
FastAPI Router (v2/products.py)
   ↓
Dependency injection (deps.py) → DB, cache, services
   ↓
Domain Service (product_svc.py)
   ↓
Repository (product_repo.py)
   ↓
MongoDB / Redis / OpenAI
```

---

## ✅ Best practices

* Keep routers as **thin as possible**: only handle request parsing, validation, and HTTP-specific concerns.
* Use **Pydantic schemas per API version** to avoid breaking existing clients.
* Place **shared dependencies** in `deps.py` so they’re easy to reuse and mock in tests.
* Document each router with **tags** for better OpenAPI grouping.

---

## 🚫 Anti-patterns

* **Business logic in routers**: makes it impossible to reuse the logic elsewhere (e.g., in workers).
* **Mixing versioned and non-versioned endpoints** in the same router.
* **Using domain models directly as response models** → breaks versioning flexibility.

---

## 📎 Useful references

* [FastAPI Routing](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
* [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
* [Versioning APIs](https://restfulapi.net/versioning/)

---

💡 **Tip**:
If you deprecate an API version, you can set HTTP headers in all its routers:

```python
@router.middleware("http")
async def add_deprecation_headers(request, call_next):
    response = await call_next(request)
    response.headers["Deprecation"] = "true"
    response.headers["Sunset"] = "2025-12-31"
    return response
```

---
