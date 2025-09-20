# 📂 `core/` — Application Core & Configuration

## 🎯 Purpose

The **`core/`** folder contains **application-wide foundational components** that everything else depends on.
It’s where you centralize:

* **Configuration** (env vars, settings, constants)
* **Logging**
* **Security** (auth, API key handling, JWT utils, password hashing)
* **Global constants** and helpers that apply to the entire app

> The **core layer** is **infrastructure-agnostic**:
> it doesn’t contain business rules, but it’s allowed to know about frameworks and infrastructure because it wires the app together.

---

## 📜 Principles

1. **Centralized config**: all env vars live in one place, easy to override per environment.
2. **Framework-aware**: can import FastAPI, logging libraries, security packages.
3. **No business logic**: only app-wide plumbing code.
4. **Reusable across services**: config, logging, and security modules should be portable to other microservices in your ecosystem.

---

## 📐 Typical structure

```
core/
  config.py      # App settings (Pydantic)
  logging.py     # Logging configuration
  security.py    # Security utilities (hashing, JWT, API keys)
```

---

## 🧩 Example: `config.py`

```python
# core/config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    app_name: str = "my-fastapi-app"
    env: str = "dev"

    # MongoDB
    mongo_uri: str
    mongo_db: str = "appdb"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # OpenAI
    openai_api_key: str
    openai_timeout_s: int = 20

    # API
    api_prefix: str = "/api"
    cors_origins: list[str] = ["*"]

    model_config = {"env_file": ".env", "extra": "ignore"}

settings = Settings()
```

---

## 🧩 Example: `logging.py`

```python
# core/logging.py
import logging
import sys

def init_logging(level=logging.INFO):
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
```

---

## 🧩 Example: `security.py`

```python
# core/security.py
from passlib.context import CryptContext
import jwt
from datetime import datetime, timedelta
from app.core.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)

def create_jwt(payload: dict, expires_delta: timedelta) -> str:
    to_encode = payload.copy()
    to_encode["exp"] = datetime.utcnow() + expires_delta
    return jwt.encode(to_encode, settings.openai_api_key, algorithm="HS256")

def decode_jwt(token: str) -> dict:
    return jwt.decode(token, settings.openai_api_key, algorithms=["HS256"])
```

---

## 🔄 Role in the overall architecture

```
Routers & Services → core.config for settings
                 → core.logging for app-wide logging
                 → core.security for authentication helpers
```

---

## ✅ Best practices

* Keep secrets in **`.env`**, never in code.
* Use **typed settings** for all config (Pydantic makes this safe).
* Apply **logging config** at app startup.
* Keep security utilities **stateless** and reusable.

---

## 🚫 Anti-patterns

* **Hardcoding credentials** in code.
* **Putting business logic in core** (e.g., product price calculation).
* **Coupling to a specific database** — database logic stays in `db/` and `repositories/`.

---

## 📎 Useful references

* [Pydantic Settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
* [FastAPI Security](https://fastapi.tiangolo.com/advanced/security/)
* [Python Logging](https://docs.python.org/3/library/logging.html)

---

💡 **Tip**:
If you have multiple services, you can extract `core/config.py` and `core/logging.py` into a shared internal Python package so all your microservices share the same conventions.

---
