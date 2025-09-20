from fastapi import FastAPI
from app.core.config import get_settings
from app.core.lifespan import lifespan
from app.api.v1.routers.products import router as products_router
from app.api.v1.routers.health import router as health_router
from app.api.v1.routers.importer import router as import_router
from app.api.v1.routers.topsales import router as top_sales_router
from app.api.v1.routers.lastseen import router as last_seen_router
from app.api.v1.routers.xsell import router as xsell_router
from app.api.v1.routers.similar import router as similar_router
from app.api.v1.routers.complementary import router as complementary_router
from app.api.v1.routers.analytics import router as analytics_router
from app.core.logging import configure_logging

from fastapi.middleware.cors import CORSMiddleware
import logging, os

settings = get_settings()
configure_logging(level=logging.DEBUG if settings.DEBUG else logging.INFO)

app = FastAPI(title=settings.APP_NAME, lifespan=lifespan)

# ------- CORS (prod-ready) -------
# Lis ALLOWED_ORIGINS depuis l'env (CSV). Exemple:
# ALLOWED_ORIGINS="https://keyvanm.cloud,https://www.keyvanm.cloud"
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
allowed_origins = [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

# Si tu veux autoriser les previews Vercel, active le regex ci-dessous.
# NB: allow_credentials=True + "*" est interdit → utilise origines listées et/ou regex.
allow_origin_regex = r"^https:\/\/.*\.vercel\.app$" if os.getenv("ALLOW_VERCEL_PREVIEWS", "false").lower() == "true" else None

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins if allowed_origins else [
        # fallback raisonnable si la variable n'est pas posée
        "https://keyvanm.cloud",
        "https://www.keyvanm.cloud",
    ],
    allow_origin_regex=allow_origin_regex,          # optionnel, pour *.vercel.app
    allow_credentials=False,                        # garde False pour simplifier le préflight
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],                            # ou ["content-type","x-api-version"]
    max_age=86400,
)

# ------- Routes -------
app.include_router(health_router)
app.include_router(products_router)          # products utilities (e.g., vectorize)
app.include_router(similar_router)           # similar
app.include_router(complementary_router)     # complementary
# app.include_router(import_router)          # not ready
app.include_router(top_sales_router)         # top sales
app.include_router(last_seen_router)         # last seen
app.include_router(xsell_router)             # xsell
app.include_router(analytics_router)
