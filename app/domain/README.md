# 📂 `domain/` — Core Business Layer (*Domain Layer*)

## 🎯 Purpose

The **`domain/`** folder contains the **pure business logic** of the application, independent from any technical concerns like HTTP, databases, caches, or AI providers.

It usually contains:

* **Domain models** (*entities* and *value objects*).
* **Repository interfaces** (contracts for data access).
* **Domain services** (business rules, workflows, orchestration).

> 💡 In Clean Architecture or Domain-Driven Design (DDD), the **domain layer** is the most stable part of the system.
> Technology and infrastructure can change, but the domain should remain the same.

---

## 📜 Principles

1. **Technology-agnostic**: no imports from `fastapi`, `motor`, `redis`, `openai`, etc.
   → Implementations are injected from the outside.
2. **Testable in isolation**: you should be able to run all domain tests without any DB or external API.
3. **Readable**: new developers should understand the business rules without digging into infrastructure code.
4. **Stable**: changes in infrastructure (DB, cache, AI provider) should not affect the domain layer.

---

## 📐 Typical structure

```
domain/
  models/          # Domain models (Pydantic or plain classes)
    product.py
    user.py
  repositories/    # Interfaces & contracts for data access
    product_repo.py
  services/        # Business logic and orchestration
    product_svc.py
    ai_svc.py
```

---

## 🔄 Typical flow

```
API Router (FastAPI)
    ↓
Domain Service (product_svc.py)
    ↓
Repository (product_repo.py)
    ↓
Database (MongoDB)
```

---

## ✅ Best practices

* **Services** can orchestrate multiple repositories, caches, and AI calls.
* **Repositories** expose clear, predictable methods (`get_by_id`, `list`, `insert`, etc.).
* **Domain models** can be:

  * **Rich entities** with small business methods.
  * Or simple Pydantic models, depending on needs.
* Use **dependency injection** to provide concrete implementations (e.g., `ProductRepo`, Redis client, OpenAI client).

---

## 🚫 Anti-patterns

* **Importing web frameworks** in the domain → couples business rules to infrastructure.
* **Direct HTTP calls** in a domain service → use a dedicated repository for external data sources.
* **Mixing responsibilities** in one file (model + repo + service together).

---

## 📐 Minimal service example

```python
# services/product_svc.py
import json
from redis.asyncio import Redis
from ..repositories.product_repo import ProductRepo

CACHE_TTL = 60

async def get_product(repo: ProductRepo, cache: Redis, pid: str) -> dict | None:
    """Retrieve a product from Redis cache or MongoDB."""
    key = f"product:{pid}"
    if val := await cache.get(key):
        return json.loads(val)
    doc = await repo.get_by_id(pid)
    if doc:
        await cache.set(key, json.dumps(doc), ex=CACHE_TTL)
    return doc
```

---

## 📎 Useful references

* [Domain-Driven Design — Martin Fowler](https://martinfowler.com/tags/domain%20driven%20design.html)
* [Clean Architecture — Uncle Bob](https://8thlight.com/blog/uncle-bob/2012/08/13/the-clean-architecture.html)

---

💡 **Tip**:
For full decoupling, define **repository interfaces** (Python `Protocol` classes) inside `domain/repositories/` and inject their concrete implementations from an `infrastructure/` layer.
That way, your business logic never directly depends on a specific database or API.

---

