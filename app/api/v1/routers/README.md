# 📂 `routers/` — HTTP Endpoints (Controllers)

## 🎯 Purpose

The **`routers/`** folder contains the **HTTP controllers** for your API.
Each router:

* Defines **HTTP endpoints** (`GET`, `POST`, `PUT`, `DELETE`, etc.).
* Maps **requests** → **services** → **responses**.
* Handles **HTTP-specific concerns** (status codes, path/query params, request bodies, response models, headers).
* Delegates all business logic to **services** in the domain layer.

---

## 📜 Principles

1. **Versioned structure**:

   * Keep routers inside `api/v1/routers/`, `api/v2/routers/`, etc.
   * One router file per **domain capability** (e.g., `products.py`, `users.py`).
2. **Thin controllers**:

   * Only validate inputs and call services.
   * No direct DB/cache calls here.
3. **Explicit schemas**:

   * Use Pydantic models from the corresponding `schemas/` folder.
4. **Clear tagging**:

   * Use `tags=[...]` in `APIRouter()` for OpenAPI grouping.

---

## 📐 Example structure

```
api/
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
```

---

## 🧩 Minimal router example

```python
# api/v1/routers/products.py
from fastapi import APIRouter, Depends, HTTPException
from app.api.deps import mongo_db, redis_dep
from app.domain.repositories.product_repo import ProductRepo
from app.domain.services.product_svc import ProductService
from app.api.v1.schemas.product import ProductOut

router = APIRouter(tags=["products"])

@router.get("/products/{pid}", response_model=ProductOut)
async def get_product(pid: str, db=Depends(mongo_db), cache=Depends(redis_dep)):
    svc = ProductService(ProductRepo(db), cache)
    doc = await svc.get_by_id(pid)
    if not doc:
        raise HTTPException(status_code=404, detail="Product not found")
    return doc
```

---

## 🧩 Health check example

```python
# api/v1/routers/health.py
from fastapi import APIRouter

router = APIRouter(tags=["health"])

@router.get("/health")
async def health():
    return {"status": "ok"}
```

---

## 🔄 Request flow

```
HTTP Request
   ↓
FastAPI Router (e.g., v1/products.py)
   ↓
Dependency injection (`deps.py`) → DB, cache, services
   ↓
Domain Service (e.g., product_svc.py)
   ↓
Repository (product_repo.py)
   ↓
Database / Cache / External APIs (MongoDB, Redis, OpenAI)
```

---

## ✅ Best practices

* Keep routers **focused** on HTTP concerns.
* Group endpoints by resource type (one router per domain entity).
* Add OpenAPI tags for better documentation grouping.
* Return typed Pydantic models for **all** responses.
* Handle deprecations via HTTP headers (`Deprecation`, `Sunset`) if needed.

---

## 🚫 Anti-patterns

* **Business logic in routers** — makes it impossible to reuse in workers or CLI tools.
* **Direct DB/cache calls** — breaks separation of concerns.
* **Reusing domain models as API schemas** — prevents API contract versioning.

---

## 📎 Useful references

* [FastAPI APIRouter](https://fastapi.tiangolo.com/tutorial/bigger-applications/)
* [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)
* [OpenAPI Tags](https://fastapi.tiangolo.com/tutorial/metadata/)

---

💡 **Tip**:
If you maintain multiple API versions, consider creating a **`router registry`** in `main.py` that imports and mounts routers dynamically for each version, so you don’t forget to register new endpoints.

---
