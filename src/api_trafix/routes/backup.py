import re
import uuid
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.config.settings import get_settings
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import backup as crud
from api_trafix.crud import system_config as config_crud
from api_trafix.models import BackupStatus, User
from api_trafix.schemas.backup import BackupPage, BackupRead, BackupRestoreRequest
from api_trafix.services import backup as service

router = APIRouter(prefix="/backups", tags=["Backup & Restore"])

_AUTO_BACKUP_SECTION = "auto_backup"


class AutoBackupConfig(BaseModel):
    enabled: bool = Field(default=True)
    time: str = Field(default="00:00", max_length=5)
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


def _effective_auto_backup(db_values: dict[str, dict], settings) -> AutoBackupConfig:
    """Merge DB overrides on top of environment defaults."""
    out: dict[str, object] = {
        "enabled": settings.daily_backup_enabled,
        "time": settings.daily_backup_time,
        "timezone": settings.daily_backup_timezone,
    }
    for key, entry in db_values.items():
        if key in out and isinstance(entry, dict) and "value" in entry:
            out[key] = entry["value"]
    return AutoBackupConfig(**out)


def _page(total: int, page: int, page_size: int) -> int:
    return (total + page_size - 1) // page_size


@router.get("/auto-backup", response_model=AutoBackupConfig)
async def auto_backup_get(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Effective daily auto-backup configuration (DB override, else env default)."""
    db_values = await config_crud.get_section(db, _AUTO_BACKUP_SECTION)
    return _effective_auto_backup(db_values, get_settings())


@router.put("/auto-backup", response_model=AutoBackupConfig)
async def auto_backup_put(
    payload: AutoBackupConfig,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    """Persist daily auto-backup configuration. Takes effect within seconds."""
    for key in ("enabled", "time", "timezone"):
        await config_crud.upsert(db, _AUTO_BACKUP_SECTION, key, {"value": getattr(payload, key)})
    db_values = await config_crud.get_section(db, _AUTO_BACKUP_SECTION)
    return _effective_auto_backup(db_values, get_settings())


@router.get("/", response_model=BackupPage)
async def list_backups(
    search: str | None = Query(default=None, max_length=100),
    status_filter: BackupStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    items, total = await crud.get_all(
        db, status_filter=status_filter, search=search, page=page, page_size=page_size
    )
    return BackupPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=_page(total, page, page_size)
    )


@router.post("/", response_model=BackupRead, status_code=status.HTTP_202_ACCEPTED)
async def create_backup(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    return await service.start_backup(db, user)


@router.post("/upload", response_model=BackupRead, status_code=status.HTTP_201_CREATED)
async def upload_backup(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    try:
        return await service.import_upload(db, user, file)
    except service.BackupError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        )


@router.get("/{backup_id}", response_model=BackupRead)
async def get_backup(
    backup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, backup_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup tidak ditemukan")
    return db_obj


@router.get("/{backup_id}/download")
async def download_backup(
    backup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, backup_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup tidak ditemukan")
    try:
        path = service.resolve_download_path(db_obj)
    except service.BackupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File backup tidak ditemukan pada disk")
    return FileResponse(path, filename=db_obj.filename, media_type="application/octet-stream")


@router.post("/{backup_id}/restore", response_model=BackupRead, status_code=status.HTTP_202_ACCEPTED)
async def restore_backup(
    backup_id: uuid.UUID,
    payload: BackupRestoreRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    if not payload.confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Pemulihan memerlukan konfirmasi (confirm: true)",
        )
    db_obj = await crud.get_by_id(db, backup_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup tidak ditemukan")
    if db_obj.status == BackupStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Operasi backup sudah berjalan",
        )
    try:
        return await service.start_restore(db, db_obj, user)
    except service.BackupError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        )


@router.delete("/{backup_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_backup(
    backup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, backup_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup tidak ditemukan")
    await service.delete_backup(db, db_obj, user)
