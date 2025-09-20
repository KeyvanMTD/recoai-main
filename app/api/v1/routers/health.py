# app/routes/health.py
import time
from fastapi import APIRouter, Depends
from app.core.config import get_settings, Settings
from pymongo import MongoClient
import redis
import subprocess

router = APIRouter()

# Store startup time for uptime
START_TIME = time.time()

def get_git_sha(short: bool = True) -> str:
    try:
        cmd = ["git", "rev-parse", "--short" if short else "HEAD"]
        return subprocess.check_output(cmd).decode("utf-8").strip()
    except Exception:
        return "unknown"

@router.get("/health")
def health(settings: Settings = Depends(get_settings)):
    """
    Health check endpoint for the application.
    - Returns basic app info, uptime, and status of dependencies (MongoDB, Redis, OpenAI API key).
    - Performs a ping to MongoDB and Redis to verify connectivity.
    - Reports errors if a service is unreachable.
    - Sets overall status: "ok" if all checks pass, "error" if any critical service fails, "degraded" otherwise.
    """
    checks = {}

    # --- Basic info ---
    checks["app_name"] = settings.APP_NAME
    checks["env"] = settings.APP_ENV 
    checks["debug"] = settings.DEBUG
    checks["version"] = settings.GIT_SHA or get_git_sha()
    checks["uptime_seconds"] = int(time.time() - START_TIME)

    # --- MongoDB check ---
    try:
        client = MongoClient(settings.MONGO_URI, serverSelectionTimeoutMS=500)
        client.admin.command("ping")
        checks["mongodb"] = "ok"
    except Exception as e:
        checks["mongodb"] = f"error: {e}"

    # --- Redis check ---
    try:
        r = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=0.5)
        r.ping()
        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    # --- External API check (optional) ---
    if settings.OPENAI_API_KEY:
        # Lightweight check – just presence of key, not full API call
        checks["openai_api_key_set"] = True
    else:
        checks["openai_api_key_set"] = False

    # --- Overall status ---
    critical = [checks.get("mongodb"), checks.get("redis")]
    if all(v == "ok" for v in critical):
        status = "ok"
    elif any(isinstance(v, str) and v.startswith("error") for v in critical):
        status = "error"
    else:
        status = "degraded"

    return {
        "status": status,
        "checks": checks,
        "timestamp": int(time.time())
    }
