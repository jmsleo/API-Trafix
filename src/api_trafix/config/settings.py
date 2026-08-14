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
    subscription_auto_expire_interval_seconds: int = 300

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

    backup_dir: str = Field(default="backups", validation_alias="BACKUP_DIR")
    backup_restore_timeout_seconds: int = 300
    backup_upload_max_mb: int = 2048

    # Gate cycle: site identity printed on tickets and used on the wire.
    site_name: str = Field(default="Trafix Parking", validation_alias="SITE_NAME")
    site_address: str = Field(default="", validation_alias="SITE_ADDRESS")
    storage_dir: str = Field(default="storage", validation_alias="STORAGE_DIR")
    api_base_url: str = Field(
        default="http://127.0.0.1:8000", validation_alias="API_BASE_URL"
    )

    # Gate cycle policies. require_plate_match off by default, because on site
    # the two cameras' plate strings genuinely disagree and refusing would
    # strand real drivers.
    require_plate_match: bool = False
    command_exit_barrier: bool = True
    lpr_timeout_seconds: float = 5.0
    lpr_retries: int = 1
    button_debounce_seconds: float = 5.0
    barrier_pulse_ms: int = 1000
    barrier_beep_ms: int = 100
    # An unregistered (or expired) RFID tap must not strand the driver at the
    # barrier: fall back to the paper-ticket flow instead of refusing.
    card_fallback_to_ticket: bool = True

    # MQTT bridge to the gate boards. Disabled by default: the gate cycle then
    # uses a NullPublisher and no broker is contacted.
    mqtt_enabled: bool = Field(default=False, validation_alias="MQTT_ENABLED")
    mqtt_host: str = Field(default="127.0.0.1", validation_alias="MQTT_HOST")
    mqtt_port: int = Field(default=1883, validation_alias="MQTT_PORT")
    mqtt_keepalive: int = Field(default=60, validation_alias="MQTT_KEEPALIVE")
    mqtt_username: str = Field(default="bssparking", validation_alias="MQTT_USERNAME")
    mqtt_password: str = Field(default="BCTDev_2025", validation_alias="MQTT_PASSWORD")
    mqtt_client_id_prefix: str = Field(
        default="api-trafix", validation_alias="MQTT_CLIENT_ID_PREFIX"
    )

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
