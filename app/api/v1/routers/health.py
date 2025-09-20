# app/routes/health.py
import time
import subprocess
from fastapi import APIRouter
from app.core.config import get_settings
from app.db import mongo
from app.db.redis import get_redis  # returns Redis instance or None

router = APIRouter()
START_TIME = time.time()


def _git_sha(short: bool = True) -> str:
    try:
        cmd = ["git", "rev-parse", "--short" if short else "HEAD"]
        return subprocess.check_output(cmd).decode().strip()
    except Exception:
        return "unknown"


@router.get("/health")
async def health():
    """
    Health check tolérant :
    - ping Mongo via Motor (async)
    - Redis 'skipped' si non configuré
    - expose infos de base + statut global
    """
    settings = get_settings()
    checks: dict[str, object] = {
        "app_name": settings.APP_NAME,
        "env": settings.APP_ENV,
        "debug": settings.DEBUG,
        "version": settings.GIT_SHA or _git_sha(),
        "uptime_seconds": int(time.time() - START_TIME),
    }

    # --- Mongo ---
    try:
        db = mongo.get_db()
        await db.command("ping")
        checks["mongodb"] = "ok"
    except Exception as e:
        checks["mongodb"] = f"error: {e}"

    # --- Redis (tolérant) ---
    try:
        r = get_redis()
        if r:
            await r.ping()
            checks["redis"] = "ok"
        else:
            checks["redis"] = "skipped"
    except Exception as e:
        checks["redis"] = f"error: {e}"

      # --- OpenAI: juste la présence de la clé
    checks["openai_api_key_set"] = bool(settings.OPENAI_API_KEY)

    # --- Status global : on ne considère *que* les checks de santé réels
    def _is_ok(v): 
        return v in ("ok", "skipped") or v is True

    health_keys = ("mongodb", "redis", "openai_api_key_set")
    status = "ok" if all(_is_ok(checks.get(k)) for k in health_keys) else "error"

    return {"status": status, "checks": checks, "timestamp": int(time.time())}

