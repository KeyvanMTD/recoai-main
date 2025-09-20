# 📂 `models/` — Domain Models & Schemas

## 🎯 Purpose

The **`models/`** folder defines the **structure and types** of the data used in the application.
Models serve to:

* **Validate** incoming data (API requests, events, background jobs)
* **Serialize** outgoing data (API responses, messages, queue payloads)
* **Document** data contracts (via OpenAPI)
* **Standardize** formats used across the domain

> Here, `models` refers to **Pydantic models** (domain models), not ORM entities.
> Since we’re using MongoDB with `motor`, models are primarily for validation, type safety, and documentation.

---

## 📜 Principles

1. **Tech-agnostic**: a model should not contain database, cache, or API client logic.
2. **Clear separation**:

   * **Input models** (Request) → what the API expects.
   * **Output models** (Response) → what the API returns.
   * **Internal models** → used only inside the domain layer.
3. **Strict validation** with Pydantic v2 (types, regex, constraints).
4. **Immutable by default** to prevent side effects.

---

## 📐 Minimal example

```python
# product.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ProductBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    price: float = Field(..., ge=0)
    description: Optional[str] = None

class ProductCreate(ProductBase):
    """Model for product creation (API input)."""
    pass

class ProductUpdate(BaseModel):
    """Model for partial product updates."""
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    price: Optional[float] = Field(None, ge=0)
    description: Optional[str] = None

class ProductOut(ProductBase):
    """Model for API responses."""
    id: str
    created_at: datetime
```

---

## 🔄 Typical usage flow

```
API Router (v1/products.py)
    ↓  (validates request with ProductCreate)
Service (product_svc.py)
    ↓  (returns a ProductOut to the router)
Repository (product_repo.py)
    ↕  (returns MongoDB dicts → mapped to ProductOut)
```

---

## ✅ Best practices

* Group models by domain (`product.py`, `user.py`) rather than one large `models.py`.
* Use `Field()` for:

  * Constraints (`min_length`, `max_length`, `ge`, `le`)
  * OpenAPI documentation (`description`, `example`)
* Keep clear distinctions between **Create**, **Update**, and **Out** models.
* Enable `ConfigDict(from_attributes=True)` if instantiating from native objects (useful with ORMs or DTOs).

---

## 🚫 Anti-patterns

* **Putting business logic inside a model**
  ❌ Bad:

  ```python
  class ProductOut(BaseModel):
      price: float
      def discounted_price(self):
          return self.price * 0.9
  ```

  ✅ Correct: perform calculations in a **service**.

* **Returning raw MongoDB dicts** from repositories
  → Always validate and serialize through a Pydantic model before returning.

---

## 📎 Useful references

* [Pydantic v2 Documentation](https://docs.pydantic.dev/)
* [FastAPI Request Body](https://fastapi.tiangolo.com/tutorial/body/)
* [Extra Models & Validation Patterns](https://fastapi.tiangolo.com/tutorial/extra-models/)

---

💡 **Tip**:
You can create a `schemas/` folder inside each API version (`api/v1/schemas/product.py`) for **version-specific** models and keep `models/` for **pure domain models**.
This avoids breaking the domain layer when you change API contracts.

---

