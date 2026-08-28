import re
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.config.settings import get_settings
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import audit_log as crud
from api_trafix.crud import system_config as config_crud
from api_trafix.models import User
from api_trafix.schemas.audit_log import AuditLogPage, AuditLogRead

router = APIRouter(prefix="/audit-logs", tags=["Audit Log"])

_AUDIT_CLEANUP_SECTION = "audit_cleanup"


class AuditCleanupConfig(BaseModel):
    enabled: bool = Field(default=True)
    weekday: int = Field(default=6, ge=0, le=6)
    time: str = Field(default="23:59", max_length=5)
    timezone: str = Field(default="Asia/Jakarta", max_length=100)

    @field_validator("time")
    @classmethod
    def _validate_time(cls, value: str) -> str:
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError('time must be in "HH:MM" 24-hour format')
        return value

    @field_validator("timezone")
    @classmethod
    def _validate_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except Exception as exc:  # noqa: BLE001 - invalid zone name
            raise ValueError(f"invalid timezone: {value}") from exc
        return value


def _effective_audit_cleanup(db_values: dict[str, dict], settings) -> AuditCleanupConfig:
    """Merge DB overrides on top of environment defaults."""
    out: dict[str, object] = {
        "enabled": settings.audit_cleanup_enabled,
        "weekday": settings.audit_cleanup_weekday,
        "time": settings.audit_cleanup_time,
        "timezone": settings.audit_cleanup_timezone,
    }
    for key, entry in db_values.items():
        if key in out and isinstance(entry, dict) and "value" in entry:
            out[key] = entry["value"]
    return AuditCleanupConfig(**out)


@router.get("/cleanup-config", response_model=AuditCleanupConfig)
async def audit_cleanup_config_get(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Effective weekly audit-log cleanup configuration (DB override, else env default)."""
    db_values = await config_crud.get_section(db, _AUDIT_CLEANUP_SECTION)
    return _effective_audit_cleanup(db_values, get_settings())


@router.put("/cleanup-config", response_model=AuditCleanupConfig)
async def audit_cleanup_config_put(
    payload: AuditCleanupConfig,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Persist weekly audit-log cleanup configuration. Takes effect within seconds."""
    for key in ("enabled", "weekday", "time", "timezone"):
        await config_crud.upsert(db, _AUDIT_CLEANUP_SECTION, key, {"value": getattr(payload, key)})
    db_values = await config_crud.get_section(db, _AUDIT_CLEANUP_SECTION)
    return _effective_audit_cleanup(db_values, get_settings())


@router.get("/", response_model=AuditLogPage)
async def list_audit_logs(
    search: str | None = Query(default=None, max_length=100),
    module: str | None = Query(default=None, max_length=50),
    action: str | None = Query(default=None, max_length=50),
    role: str | None = Query(default=None, max_length=20),
    user_id: uuid.UUID | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    items, total = await crud.get_all(
        db,
        search=search,
        module=module,
        action=action,
        role=role,
        user_id=user_id,
        date_from=date_from,
        date_to=date_to,
        page=page,
        page_size=page_size,
    )
    total_pages = (total + page_size - 1) // page_size
    return AuditLogPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{audit_id}", response_model=AuditLogRead)
async def get_audit_log(
    audit_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, audit_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Log audit tidak ditemukan")
    return db_obj
