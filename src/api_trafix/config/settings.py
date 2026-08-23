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
    redis_max_connections: int = Field(
        default=100, validation_alias="REDIS_MAX_CONNECTIONS"
    )
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

    # Bootstrap admin account, seeded at startup only while no user exists.
    # Change ADMIN_PASSWORD in production; the default is for fresh installs.
    admin_name: str = Field(default="Administrator", validation_alias="ADMIN_NAME")
    admin_username: str = Field(default="admin", validation_alias="ADMIN_USERNAME")
    admin_password: str = Field(default="admin123", validation_alias="ADMIN_PASSWORD")

    max_request_size_mb: int = 1

    backup_dir: str = Field(default="backups", validation_alias="BACKUP_DIR")
    backup_restore_timeout_seconds: int = 300
    backup_upload_max_mb: int = 2048

    # Daily scheduled backup. Runs every day at ``daily_backup_time`` in
    # ``daily_backup_timezone`` (default: 00:00 WIB).
    daily_backup_enabled: bool = Field(default=True, validation_alias="DAILY_BACKUP_ENABLED")
    daily_backup_time: str = Field(default="00:00", validation_alias="DAILY_BACKUP_TIME")
    daily_backup_timezone: str = Field(default="Asia/Jakarta", validation_alias="DAILY_BACKUP_TIMEZONE")

    # Weekly audit-log cleanup. Deletes ALL audit logs every ``audit_cleanup_weekday``
    # (0=Mon..6=Sun) at ``audit_cleanup_time`` in ``audit_cleanup_timezone``
    # (default: every Sunday 23:59 WIB).
    audit_cleanup_enabled: bool = Field(default=True, validation_alias="AUDIT_CLEANUP_ENABLED")
    audit_cleanup_weekday: int = Field(default=6, validation_alias="AUDIT_CLEANUP_WEEKDAY")
    audit_cleanup_time: str = Field(default="23:59", validation_alias="AUDIT_CLEANUP_TIME")
    audit_cleanup_timezone: str = Field(default="Asia/Jakarta", validation_alias="AUDIT_CLEANUP_TIMEZONE")

    signage_media_dir: str = Field(default="media/signages", validation_alias="SIGNAGE_MEDIA_DIR")
    signage_upload_max_mb: int = 50
    signage_allowed_image_extensions: str = "jpg,jpeg,png,gif,webp"
    signage_allowed_video_extensions: str = "mp4,mov"
    signage_broadcast_sync_interval_seconds: int = 60

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
    # Push-style LPR (ECV86 camera): how long the ticket button waits for a
    # buffered plate before printing one without it, and how old a buffered
    # plate may be before it is considered a different car.
    lpr_plate_wait_seconds: float = 3.0
    lpr_plate_max_age_seconds: float = 30.0

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

    # TCP gateway for gate controllers that speak raw TCP instead of MQTT.
    tcp_enabled: bool = Field(default=False, validation_alias="TCP_ENABLED")
    tcp_default_port: int = Field(default=5000, validation_alias="TCP_DEFAULT_PORT")
    tcp_heartbeat_interval_seconds: float = Field(
        default=30.0, validation_alias="TCP_HEARTBEAT_INTERVAL"
    )
    tcp_heartbeat_fail_threshold: int = Field(
        default=3, validation_alias="TCP_HEARTBEAT_FAIL_THRESHOLD"
    )
    tcp_reconnect_interval_seconds: float = Field(
        default=5.0, validation_alias="TCP_RECONNECT_INTERVAL"
    )
    tcp_reconnect_max_retries: int = Field(
        default=3, validation_alias="TCP_RECONNECT_MAX_RETRIES"
    )

    # Signage display (pw-signage) publishing. The display app runs against the
    # legacy broker and may be migrated later, so messages mirror to every
    # configured broker. ``signage_public_base_url`` is what the display uses to
    # fetch uploaded media files.
    signage_public_base_url: str = Field(
        default="http://192.168.1.13:8000",
        validation_alias="SIGNAGE_PUBLIC_BASE_URL",
    )
    signage_legacy_brokers: list[dict[str, object]] = Field(
        default=[
            {
                "host": "192.168.1.1",
                "port": 1883,
                "username": "bssparking",
                "password": "BCTDev_2025",
            }
        ],
        validation_alias="SIGNAGE_LEGACY_BROKERS",
    )
    signage_sync_interval_seconds: float = Field(
        default=60.0, validation_alias="SIGNAGE_SYNC_INTERVAL_SECONDS"
    )

    allowed_origins: list[str] = Field(
        default=["*"],
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
