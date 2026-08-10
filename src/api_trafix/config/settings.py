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
    debug: bool = False

    database_url: str = Field(default="", validation_alias="DATABASE_URL")
    redis_url: str = Field(default="", validation_alias="REDIS_URL")
    redis_session_expire: int = 3600
    redis_cache_expire: int = 300

    secret_key: str = Field(default="", validation_alias="SECRET_KEY")
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "api-trafix"
    jwt_audience: str = "api-trafix-api"
    access_token_expire_minutes: int = 30
    refresh_token_expire_days: int = 7

    login_max_attempts: int = 5
    login_lockout_seconds: int = 900
    login_ip_rate_limit: int = 20

    max_request_size_mb: int = 1

    allowed_origins: list[str] = Field(
        default=["http://localhost:5173", "http://localhost:3000"],
        validation_alias="ALLOWED_ORIGINS",
    )

    @model_validator(mode="after")
    def _validate_required(self):
        if not self.database_url or not self.redis_url:
            raise ValueError("DATABASE_URL and REDIS_URL must be set in .env")
        if not self.secret_key:
            raise ValueError("SECRET_KEY must be set in .env")
        if self.login_lockout_seconds <= 0 or self.login_max_attempts <= 0:
            raise ValueError("login_lockout_seconds and login_max_attempts must be positive")
        if self.max_request_size_mb <= 0:
            raise ValueError("max_request_size_mb must be positive")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
