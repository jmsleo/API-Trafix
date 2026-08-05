from functools import lru_cache

from pydantic import Field, model_validator
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

    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    redis_url: str = Field(default="", validation_alias="REDIS_URL")
    redis_session_expire: int = 3600
    redis_cache_expire: int = 300

    @model_validator(mode="after")
    def _validate_required(self):
        if not self.database_url or not self.redis_url:
            raise ValueError("DATABASE_URL and REDIS_URL must be set in .env")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
