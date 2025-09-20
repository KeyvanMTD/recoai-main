# 📂 `schemas/` — API Data Contracts (Pydantic Models)

## 🎯 Purpose

The **`schemas/`** folder contains **API-specific** Pydantic models that define:

* The **shape of request bodies** your API accepts.
* The **structure of responses** your API returns.
* Any **query parameter objects** or reusable input/output models.

These schemas:

* Are **versioned** along with the API (`api/v1/schemas`, `api/v2/schemas`).
* Represent the **public contract** of your API — clients depend on them.
* Are **separate from domain models** in `domain/models` to allow API evolution without breaking the domain.

---

## 📜 Principles

1. **One source of truth** for API contracts: all input/output validation is here.
2. **Version isolation**: each API version has its own `schemas/` folder to avoid breaking old clients.
3. **Clear naming**:

   * `SomethingCreate` → for creation payloads.
   * `SomethingUpdate` → for partial updates.
   * `SomethingOut` → for responses.
4. **Validation**: use `Field()` to enforce constraints and improve OpenAPI docs.

---

## 📐 Example structure

```
api/
  v1/
    schemas/
      product.py
      user.py
  v2/
    schemas/
      product.py
```

---

## 🧩 Minimal schema example

```python
# api/v1/schemas/product.py
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

class ProductBase(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    price: float = Field(..., ge=0)
    description: Optional[str] = None

class ProductCreate(ProductBase):
    """Payload for creating a product."""
    pass

class ProductUpdate(BaseModel):
    """Payload for updating a product."""
    name: Optional[str] = Field(None, min_length=2, max_length=200)
    price: Optional[float] = Field(None, ge=0)
    description: Optional[str] = None

class ProductOut(ProductBase):
    """Response model for returning a product."""
    id: str
    created_at: datetime
```

---

## 🔄 How schemas fit into the flow

```
Router (v1/products.py)
   ↓
Parses request body → ProductCreate
Calls domain service
   ↓
Domain service returns dict / domain model
Router converts it → ProductOut
   ↓
FastAPI serializes to JSON for client
```

---

## ✅ Best practices

* Keep API schemas **separate** from domain models.
* Use `Field()` to set:

  * Validation constraints (length, min/max values, regex, etc.)
  * OpenAPI metadata (`description`, `example`)
* Default to **immutable models** (`ConfigDict(frozen=True)`) unless you need mutability.
* Keep **response models minimal** — avoid exposing internal DB fields (e.g., `_id`, `internal_notes`).

---

## 🚫 Anti-patterns

* **Reusing domain models directly** → makes it hard to change API contracts without breaking the domain.
* **Mixing multiple resources in one schema file** → split by resource for maintainability.
* **Putting business logic here** → only validation & doc generation, no calculations.

---

## 📎 Useful references

* [FastAPI Request Body](https://fastapi.tiangolo.com/tutorial/body/)
* [Pydantic v2 Docs](https://docs.pydantic.dev/)
* [OpenAPI Schema Docs](https://fastapi.tiangolo.com/tutorial/schema-extra-example/)

---

💡 **Tip**:
When bumping an API version, **copy** the existing schema file to the new `schemas/` folder and change only what’s necessary.
This preserves backward compatibility while allowing safe evolution of your API.

---
