import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import backup as crud
from api_trafix.models import BackupStatus, User
from api_trafix.schemas.backup import BackupPage, BackupRead, BackupRestoreRequest
from api_trafix.services import backup as service

router = APIRouter(prefix="/backups", tags=["Backup & Restore"])


def _page(total: int, page: int, page_size: int) -> int:
    return (total + page_size - 1) // page_size


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    return db_obj


@router.get("/{backup_id}/download")
async def download_backup(
    backup_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, backup_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    try:
        path = service.resolve_download_path(db_obj)
    except service.BackupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup file not found on disk")
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
            detail="Restore requires confirmation (confirm: true)",
        )
    db_obj = await crud.get_by_id(db, backup_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    if db_obj.status == BackupStatus.RUNNING:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Backup operation already in progress",
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Backup not found")
    await service.delete_backup(db, db_obj, user)
