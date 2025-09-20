# app/core/config.py
from functools import lru_cache
from typing import Literal, Optional
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvName = Literal["development", "production"]

def _env_file_for(app_env: EnvName) -> str:
    return ".env.development" if app_env == "development" else ".env.production"

class Settings(BaseSettings):
    # -------- Core --------
    APP_ENV: EnvName = "development"
    APP_NAME: str = "RecommendationAI"
    DEBUG: bool = False                     # <- défaut pour éviter le crash
    GIT_SHA: str = "unknown"

    # -------- Mongo --------
    MONGO_URI: str = ""                     # <- défaut vide (on loguera un warning si besoin)
    MONGO_DB: str = "mydb"

    # -------- Redis (OPTIONNEL) --------
    REDIS_URL: Optional[str] = None         # <- optionnel

    # -------- Caches --------
    vector_cache_ttl: int = 24 * 3600
    vector_cache_prefix: str = "vec"
    vector_lock_ttl: int = 20

    product_cache_ttl: int = 24 * 3600
    x_sell_cache_ttl: int = 24 * 3600
    top_sales_cache_ttl: int = 5 * 60

    # -------- OpenAI --------
    OPENAI_API_KEY: str = ""               # <- défaut vide
    openai_timeout_s: int = 30
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_RAG_MODEL: str = "gpt-4o-mini"

    # -------- API --------
    api_prefix: str = "/api"

    # pydantic-settings
    model_config = SettingsConfigDict(
        env_file=None,
        case_sensitive=True,
        extra="ignore",                    # ignore les vars non utilisées (ex: anciennes)
    )

@lru_cache
def get_settings() -> Settings:
    """
    Charge la config en choisissant .env.development ou .env.production
    selon APP_ENV, puis surcharge avec les variables d'environnement.
    """
    app_env: EnvName = os.getenv("APP_ENV", "development")
    env_file = _env_file_for(app_env)
    return Settings(_env_file=env_file, _env_file_encoding="utf-8")
