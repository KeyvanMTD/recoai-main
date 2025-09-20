# 📂 `utils/` — Cross-cutting Utilities (No Business Logic)

## 🎯 Purpose

`utils/` hosts **reusable, framework-agnostic helpers** shared across the app:

* **Cache primitives** (Redis helpers)
* **Pagination helpers** (limit/offset, Link headers)
* **Error utilities** (domain → HTTP mapping glue)
* **Serialization/ID/time helpers** (safe JSON, ULIDs/UUIDs, UTC time)

> Keep it **stateless** and **generic**. If it starts to know about your domain, it belongs in `services/` (or a repo).

---

## 📜 Principles

1. **No business rules** — only plumbing.
2. **Small, composable functions** — easy to test and reuse.
3. **Pure or side-effect conscious** — explicit I/O (e.g., pass the Redis client in).
4. **Typed** — proper type hints for IDE/CI happiness.

---

## 📐 Suggested structure

```
utils/
  cache.py         # Generic Redis helpers (get/set/delete, JSON, patterns)
  pagination.py    # Page math, link header builder, Pydantic Page model
  errors.py        # Base app errors, mapping helpers (no FastAPI import)
  ids.py           # UUID/ULID generators, safe parsing
  jsonx.py         # Robust JSON (orjson fallback), dumps/loads
  time.py          # UTC now(), ttl helpers, parsing ISO8601
```

> Start small (e.g., `cache.py`, `pagination.py`, `errors.py`) and add modules only when reuse emerges.

---

## 🧩 Examples

### 1) `cache.py` — generic Redis helpers

```python
# utils/cache.py
from __future__ import annotations
from typing import Any, Callable, Optional
from redis.asyncio import Redis
import json

def _default_dumps(x: Any) -> str:
    return json.dumps(x, separators=(",", ":"), ensure_ascii=False)

def _default_loads(s: str) -> Any:
    return json.loads(s)

async def cache_get(redis: Redis, key: str, loads: Callable[[str], Any] = _default_loads) -> Any | None:
    if raw := await redis.get(key):
        return loads(raw)
    return None

async def cache_set(
    redis: Redis,
    key: str,
    value: Any,
    ex: int | None = 60,
    dumps: Callable[[Any], str] = _default_dumps,
) -> None:
    await redis.set(key, dumps(value), ex=ex)

async def cache_delete(redis: Redis, key: str) -> None:
    await redis.delete(key)

async def cache_mdelete(redis: Redis, prefix: str) -> int:
    """Delete all keys matching 'prefix*' (cursor-scan safe)."""
    count = 0
    async for k in redis.scan_iter(match=f"{prefix}*"):
        count += await redis.delete(k)
    return count
```

**When to use:** from a **service**, not a repository. Keep TTLs/keys strategy inside the service.

---

### 2) `pagination.py` — limits, offsets, link headers

```python
# utils/pagination.py
from dataclasses import dataclass
from typing import Sequence
from math import ceil

DEFAULT_LIMIT = 20
MAX_LIMIT = 100

@dataclass(slots=True)
class PageMeta:
    total: int
    limit: int
    offset: int
    pages: int

def clamp_limit(limit: int | None) -> int:
    if not limit or limit <= 0:
        return DEFAULT_LIMIT
    return min(limit, MAX_LIMIT)

def build_meta(total: int, limit: int, offset: int) -> PageMeta:
    pages = ceil(max(total, 0) / max(limit, 1))
    return PageMeta(total=total, limit=limit, offset=offset, pages=pages)

def build_link_header(base_url: str, meta: PageMeta) -> str:
    links = []
    def u(o): return f'{base_url}?limit={meta.limit}&offset={o}'
    # first/prev
    links.append(f'<{u(0)}>; rel="first"')
    if meta.offset > 0:
        prev = max(meta.offset - meta.limit, 0)
        links.append(f'<{u(prev)}>; rel="prev"')
    # next/last
    next_off = meta.offset + meta.limit
    if next_off < meta.total:
        links.append(f'<{u(next_off)}>; rel="next"')
    last_off = max((meta.pages - 1) * meta.limit, 0)
    links.append(f'<{u(last_off)}>; rel="last"')
    return ", ".join(links)
```

**Usage pattern (router):**

```python
# inside a router handler
limit = clamp_limit(limit)
meta = build_meta(total=count, limit=limit, offset=offset)
response.headers["X-Total-Count"] = str(meta.total)
response.headers["Link"] = build_link_header(request.url.path, meta)
```

---

### 3) `errors.py` — app errors & mapping glue

```python
# utils/errors.py
class AppError(Exception):
    """Base application error."""

class NotFound(AppError): ...
class Conflict(AppError): ...
class Forbidden(AppError): ...
class BadRequest(AppError): ...

# Optional: mapping table (used by API layer to map -> HTTP)
HTTP_MAP = {
    NotFound: 404,
    Conflict: 409,
    Forbidden: 403,
    BadRequest: 400,
}
```

**Why here?** Services can raise `AppError` without importing FastAPI.
API layer translates `AppError` → `HTTPException` using `HTTP_MAP`.

---

### 4) `ids.py` — safe IDs (UUID/ULID)

```python
# utils/ids.py
import uuid

def new_uuid() -> str:
    return str(uuid.uuid4())

def is_uuid(s: str) -> bool:
    try:
        uuid.UUID(s)
        return True
    except Exception:
        return False
```

(If you prefer ULIDs, add a tiny ulid generator; keep it dependency-light.)

---

### 5) `jsonx.py` — robust JSON with optional orjson

```python
# utils/jsonx.py
from typing import Any
try:
    import orjson
    def dumps(v: Any) -> str: return orjson.dumps(v).decode()
    def loads(s: str) -> Any: return orjson.loads(s)
except Exception:
    import json
    def dumps(v: Any) -> str: return json.dumps(v, separators=(",", ":"), ensure_ascii=False)
    def loads(s: str) -> Any: return json.loads(s)
```

---

### 6) `time.py` — UTC utilities

```python
# utils/time.py
from datetime import datetime, timezone, timedelta

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def ttl_seconds(minutes: int = 5) -> int:
    return int(timedelta(minutes=minutes).total_seconds())
```

---

## ✅ Best practices

* Keep helpers **tiny** and **single-purpose**.
* **No imports from FastAPI/Starlette/Motor/OpenAI** here.
* Reuse across services; don’t leak domain terms in util names.
* Unit test each module with **fast tests** (no network, no DB).

---

## 🚫 Anti-patterns

* Embedding business rules (e.g., *“member price = 0.9x”*) → belongs in a service.
* Hiding I/O (creating Redis/Mongo clients here) → connection lives in `db/`.
* God-modules (`utils/helpers.py` with 100+ functions) → split by concern.

---

## 🧪 Testing tips

* Pure utils ⇒ **pytest** with straightforward asserts.
* For `cache.py`, use a **fake Redis** object (dict-backed) in unit tests.
* Property-based tests for `ids.py` and `pagination.py` edge cases (offset/limit math).

---

## 📎 References

* RFC 5988 (Web Linking) for pagination `Link` header
* Redis SCAN patterns for safe deletions
* Pydantic & FastAPI docs (for how utils plug into routers/services)

---
