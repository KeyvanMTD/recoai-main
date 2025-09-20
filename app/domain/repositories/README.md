# 📂 `repositories/` — Data Access Layer (DAL)

## 🎯 Purpose

**Repositories** handle **data persistence and retrieval** from any data source:

* **MongoDB** (via `motor`)
* **Redis** (if reading/writing directly to cache)
* **External APIs** (if acting as a data source)

> **Important**:
> A repository contains **no business logic**.
> It only **reads/writes** data and returns it in a predictable format.

---

## 📜 Principles

1. **Isolation**: other parts of the app should not know database specifics.
2. **Testability**: you can mock a repository without needing a real DB.
3. **Consistency**: method naming should be uniform (`get_by_id`, `list`, `insert`, `update`, `delete`).
4. **No circular dependencies**: repositories must not import services.

---

## 📐 Minimal example

```python
# product_repo.py
from typing import Sequence
from motor.motor_asyncio import AsyncIOMotorDatabase

class ProductRepo:
    def __init__(self, db: AsyncIOMotorDatabase):
        self.col = db["products"]

    async def get_by_id(self, pid: str) -> dict | None:
        """Return a product by its MongoDB ID."""
        return await self.col.find_one({"_id": pid})

    async def list(self, limit: int = 20, skip: int = 0) -> Sequence[dict]:
        """Return a list of products without heavy fields."""
        cursor = self.col.find({}, projection={"description": 0}).skip(skip).limit(limit)
        return [doc async for doc in cursor]

    async def insert(self, data: dict) -> str:
        """Insert a product and return its ID."""
        result = await self.col.insert_one(data)
        return str(result.inserted_id)
```

---

## 🔄 Typical call flow

```
API Router (v1/products.py)
    ↓
Service (product_svc.py)
    ↓
Repository (product_repo.py)
    ↓
MongoDB
```

---

## ✅ Best practices

* Always receive a DB instance (`AsyncIOMotorDatabase`) via **dependency injection** (FastAPI’s `Depends`).
* No direct Pydantic conversion here → conversion happens in the service or API layer.
* Keep indexing & migrations in a dedicated `db/migrations.py`, not in the repository itself.
* Avoid global try/except → let errors bubble up so the service or middleware can handle them.

---

## 🚫 Anti-patterns

* **Business logic inside a repository**
  ❌ Bad:

  ```python
  async def get_price_with_discount(...):
      doc = await self.col.find_one({"_id": pid})
      return doc["price"] * 0.9
  ```

  ✅ Correct: do this calculation in a **service**.

* **Cache logic inside a repository**
  → Keep caching in the **service layer** to centralize strategy.

---

## 📎 Useful references

* [`motor` AsyncIO MongoDB Driver](https://motor.readthedocs.io/)
* [Clean Architecture](https://8thlight.com/blog/uncle-bob/2012/08/13/the-clean-architecture.html)
* [FastAPI Dependencies](https://fastapi.tiangolo.com/tutorial/dependencies/)

---

💡 **Tip**:
If your app can have multiple data sources (e.g., Mongo + external API),
create multiple repositories that **implement the same interface** (`IProductRepo`) and inject the desired one at runtime.

---

