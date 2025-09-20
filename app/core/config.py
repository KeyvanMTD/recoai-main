from functools import lru_cache
from typing import Literal
import os
from pydantic_settings import BaseSettings, SettingsConfigDict

EnvName = Literal["development", "production"]

def _env_file_for(app_env: EnvName) -> str:
    return ".env.development" if app_env == "development" else ".env.production"

class Settings(BaseSettings):

    # Core
    APP_ENV: EnvName = "development"
    APP_NAME: str = "RecommendationAI"
    DEBUG: bool # ✅ declared
    GIT_SHA: str = "unknown"

    # Mongo
    MONGO_URI: str # ✅ declared
    MONGO_DB: str # ✅ declared

    # Redis
    REDIS_URL: str # ✅ declared

    # Vector cache config
    vector_cache_ttl: int = 24 * 3600          # 24h (tune per your SLA)
    vector_cache_prefix: str = "vec"           # redis key namespace
    vector_lock_ttl: int = 20                  # seconds; dogpile protection

    # Cache config
    product_cache_ttl: int = 24 * 3600            # 24 hours
    x_sell_cache_ttl: int = 24 * 3600            # 24 hours
    top_sales_cache_ttl: int = 5 * 60            # 5 minutes

    # OpenAI
    OPENAI_API_KEY: str # ✅ declared
    openai_timeout_s: int = 30  # seconds
    OPENAI_EMBEDDING_MODEL: str # ✅ declared
    OPENAI_RAG_MODEL: str # ✅ declared

    # API
    api_prefix: str = "/api"

    # pydantic-settings config will be set dynamically in the factory below
    model_config = SettingsConfigDict(env_file=None, case_sensitive=True)

@lru_cache
def get_settings() -> Settings:
    """
    Factory that chooses the right .env file based on APP_ENV.
    Cache makes it cheap to inject via FastAPI dependencies.
    """
    app_env: EnvName = os.getenv("APP_ENV", "development")  # earliest switch
    env_file = _env_file_for(app_env)
    return Settings(
                _env_file=env_file,  # load .env.development or .env.production
                _env_file_encoding="utf-8"
    )

