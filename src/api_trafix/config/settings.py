from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "api-trafix"
    app_env: str = "development"
    app_version: str = "1.0.0"
    debug: bool = True

    database_url: str = Field(validation_alias="DATABASE_URL")
    redis_url: str = Field(validation_alias="REDIS_URL")
    redis_session_expire: int = 3600
    redis_cache_expire: int = 300


@lru_cache
def get_settings() -> Settings:
    return Settings()
