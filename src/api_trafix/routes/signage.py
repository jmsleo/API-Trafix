import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import async_session_maker, get_db
from api_trafix.config.settings import get_settings
from api_trafix.core.dependencies import get_current_admin_or_teknisi
from api_trafix.crud import signage as crud
from api_trafix.models import SignageContentType, User
from api_trafix.services import signage_media as media_service
from api_trafix.services.audit import log_action

from api_trafix.schemas.signage import (
    SignageAssignmentCreate,
    SignageAssignmentPage,
    SignageAssignmentRead,
    SignageAssignmentStatusUpdate,
    SignageContentCreate,
    SignageContentPage,
    SignageContentRead,
    SignageContentStatusUpdate,
    SignageContentUpdate,
    SignageCreate,
    SignagePage,
    SignageRead,
    SignageScheduleCreate,
    SignageSchedulePage,
    SignageScheduleRead,
    SignageScheduleStatusUpdate,
    SignageScheduleUpdate,
    SignageStatus,
    SignageStatusUpdate,
    SignageUpdate,
)

router = APIRouter(prefix="/signages", tags=["Signage"])

logger = logging.getLogger(__name__)


async def _trigger_signage_sync(request: Request) -> None:
    """Fire-and-forget push of current signage content to the displays."""
    publisher = getattr(request.app.state, "signage_publisher", None)
    if publisher is None:
        return
    try:
        async with async_session_maker() as db:
            await publisher.sync_from_db(db)
    except Exception:
        logger.exception("signage sync after content change failed")


def _page(total: int, page: int, page_size: int) -> int:
    return (total + page_size - 1) // page_size


# ---------------------------------------------------------------------------
# Signage Management
# ---------------------------------------------------------------------------
@router.get("/", response_model=SignagePage)
async def list_signages(
    search: str | None = Query(default=None, max_length=100),
    status_filter: SignageStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await crud.get_all_signages(
        db, search=search, status=status_filter, page=page, page_size=page_size
    )
    return SignagePage(
        items=items, total=total, page=page, page_size=page_size, total_pages=_page(total, page, page_size)
    )


@router.post("/", response_model=SignageRead, status_code=status.HTTP_201_CREATED)
async def create_signage(
    request: Request,
    payload: SignageCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    existing = await crud.get_signage_by_code(db, payload.code)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kode sudah digunakan")
    db_obj = await crud.create_signage(db, payload)
    await log_action(db, module="signage", action="create", user_id=current_user.id,
                     role=current_user.role.value, description=f"Created signage '{db_obj.name}' ({db_obj.code})")
    asyncio.create_task(_trigger_signage_sync(request))
    return db_obj


# ---------------------------------------------------------------------------
# Content Management
# ---------------------------------------------------------------------------
@router.get("/contents", response_model=SignageContentPage)
async def list_contents(
    search: str | None = Query(default=None, max_length=100),
    content_type: str | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    type_filter = None
    if content_type is not None:
        try:
            type_filter = SignageContentType(content_type)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"content_type tidak valid, harus salah satu dari {[t.value for t in SignageContentType]}",
            )
    items, total = await crud.get_all_contents(
        db, search=search, content_type=type_filter, is_active=is_active, page=page, page_size=page_size
    )
    return SignageContentPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=_page(total, page, page_size)
    )


@router.get("/contents/{content_id}", response_model=SignageContentRead)
async def get_content(content_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_content(db, content_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konten signage tidak ditemukan")
    return db_obj


@router.post("/contents", response_model=SignageContentRead, status_code=status.HTTP_201_CREATED)
async def create_content(
    request: Request,
    payload: SignageContentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.create_content(db, payload)
    await log_action(db, module="signage", action="create-content", user_id=current_user.id,
                     role=current_user.role.value, description=f"Created signage content '{db_obj.title}'")
    asyncio.create_task(_trigger_signage_sync(request))
    return db_obj


@router.put("/contents/{content_id}", response_model=SignageContentRead)
async def update_content(
    request: Request,
    content_id: uuid.UUID,
    payload: SignageContentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_content(db, content_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konten signage tidak ditemukan")
    db_obj = await crud.update_content(db, db_obj, payload)
    await log_action(db, module="signage", action="update-content", user_id=current_user.id,
                     role=current_user.role.value, description=f"Updated signage content '{db_obj.title}'")
    asyncio.create_task(_trigger_signage_sync(request))
    return db_obj


@router.patch("/contents/{content_id}/status", response_model=SignageContentRead)
async def update_content_status(
    request: Request,
    content_id: uuid.UUID,
    payload: SignageContentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_content(db, content_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konten signage tidak ditemukan")
    db_obj = await crud.update_content(db, db_obj, payload)
    await log_action(db, module="signage", action="update-content-status", user_id=current_user.id,
                     role=current_user.role.value,
                     description=f"Changed signage content '{db_obj.title}' active status to {db_obj.is_active}")
    asyncio.create_task(_trigger_signage_sync(request))
    return db_obj


@router.post("/contents/upload", response_model=SignageContentRead, status_code=status.HTTP_201_CREATED)
async def upload_content(
    request: Request,
    file: UploadFile = File(...),
    title: str = Form(...),
    content_type: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    try:
        type_filter = SignageContentType(content_type)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"content_type tidak valid, harus salah satu dari {[t.value for t in SignageContentType]}",
        )

    try:
        mime = media_service.validate_upload(type_filter, file.filename)
    except media_service.SignageMediaError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    max_bytes = get_settings().signage_upload_max_mb * 1024 * 1024
    total = 0
    chunks: list[bytes] = []
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"File melebihi batas {get_settings().signage_upload_max_mb} MB",
            )
        chunks.append(chunk)

    if total == 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="File yang diunggah kosong")

    stored_name = media_service.save_upload(type_filter, mime, b"".join(chunks), file.filename)
    db_obj = await crud.create_media_content(
        db,
        title=title.strip(),
        content_type=type_filter,
        mime_type=mime,
        file_path=stored_name,
        file_size_bytes=total,
    )
    await log_action(db, module="signage", action="upload-content", user_id=current_user.id,
                     role=current_user.role.value,
                     description=f"Uploaded signage content '{db_obj.title}' ({type_filter.value}, {total} bytes)")
    asyncio.create_task(_trigger_signage_sync(request))
    return db_obj


@router.get("/contents/{content_id}/file")
async def get_content_file(content_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_content(db, content_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konten signage tidak ditemukan")
    if db_obj.file_path is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konten tidak memiliki file media")
    try:
        path = media_service.resolve_content_file(db_obj)
    except media_service.SignageMediaError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File media tidak ditemukan pada disk")
    return FileResponse(path, media_type=db_obj.mime_type or "application/octet-stream", filename=path.name)


@router.delete("/contents/{content_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_content(
    request: Request,
    content_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_content(db, content_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konten signage tidak ditemukan")
    if await crud.is_content_in_use(db, content_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Konten sedang digunakan oleh penugasan atau jadwal",
        )
    await log_action(db, module="signage", action="delete-content", user_id=current_user.id,
                     role=current_user.role.value, description=f"Deleted signage content '{db_obj.title}'")
    await crud.delete_content(db, db_obj)
    media_service.delete_content_file(db_obj)
    asyncio.create_task(_trigger_signage_sync(request))
    return None


# ---------------------------------------------------------------------------
# Content Assignment
# ---------------------------------------------------------------------------
@router.get("/assignments", response_model=SignageAssignmentPage)
async def list_assignments(
    signage_id: uuid.UUID | None = Query(default=None),
    content_id: uuid.UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await crud.get_all_assignments(
        db,
        signage_id=signage_id,
        content_id=content_id,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return SignageAssignmentPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=_page(total, page, page_size)
    )


@router.get("/assignments/{assignment_id}", response_model=SignageAssignmentRead)
async def get_assignment(assignment_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_assignment(db, assignment_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Penugasan tidak ditemukan")
    return db_obj


@router.post("/assignments", response_model=SignageAssignmentRead, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    request: Request,
    payload: SignageAssignmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    signage = await crud.get_signage(db, payload.signage_id)
    if signage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signage tidak ditemukan")
    content = await crud.get_content(db, payload.content_id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konten signage tidak ditemukan")
    existing = await crud.get_assignment_by_pair(db, payload.signage_id, payload.content_id)
    if existing is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Konten ini sudah ditugaskan ke signage",
        )
    try:
        db_obj = await crud.create_assignment(db, payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Konten ini sudah ditugaskan ke signage",
        )
    await log_action(db, module="signage", action="create-assignment", user_id=current_user.id,
                     role=current_user.role.value,
                     description=f"Assigned content '{content.title}' to signage '{signage.name}'")
    asyncio.create_task(_trigger_signage_sync(request))
    return db_obj


@router.patch("/assignments/{assignment_id}/status", response_model=SignageAssignmentRead)
async def update_assignment_status(
    request: Request,
    assignment_id: uuid.UUID,
    payload: SignageAssignmentStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_assignment(db, assignment_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Penugasan tidak ditemukan")
    db_obj = await crud.update_assignment(db, db_obj, payload)
    await log_action(db, module="signage", action="update-assignment-status", user_id=current_user.id,
                     role=current_user.role.value,
                     description=f"Changed signage assignment active status to {db_obj.is_active}")
    asyncio.create_task(_trigger_signage_sync(request))
    return db_obj


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment(
    request: Request,
    assignment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_assignment(db, assignment_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Penugasan tidak ditemukan")
    await log_action(db, module="signage", action="delete-assignment", user_id=current_user.id,
                     role=current_user.role.value,
                     description=f"Deleted signage assignment (signage '{db_obj.signage.name}', content '{db_obj.content.title}')")
    await crud.delete_assignment(db, db_obj)
    asyncio.create_task(_trigger_signage_sync(request))
    return None


# ---------------------------------------------------------------------------
# Content Scheduling
# ---------------------------------------------------------------------------
@router.get("/schedules", response_model=SignageSchedulePage)
async def list_schedules(
    signage_id: uuid.UUID | None = Query(default=None),
    content_id: uuid.UUID | None = Query(default=None),
    is_active: bool | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    items, total = await crud.get_all_schedules(
        db,
        signage_id=signage_id,
        content_id=content_id,
        is_active=is_active,
        page=page,
        page_size=page_size,
    )
    return SignageSchedulePage(
        items=items, total=total, page=page, page_size=page_size, total_pages=_page(total, page, page_size)
    )


@router.get("/schedules/{schedule_id}", response_model=SignageScheduleRead)
async def get_schedule(schedule_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_schedule(db, schedule_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jadwal tidak ditemukan")
    return db_obj


@router.post("/schedules", response_model=SignageScheduleRead, status_code=status.HTTP_201_CREATED)
async def create_schedule(
    payload: SignageScheduleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    signage = await crud.get_signage(db, payload.signage_id)
    if signage is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signage tidak ditemukan")
    content = await crud.get_content(db, payload.content_id)
    if content is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konten signage tidak ditemukan")
    db_obj = await crud.create_schedule(db, payload)
    await log_action(db, module="signage", action="create-schedule", user_id=current_user.id,
                     role=current_user.role.value,
                     description=f"Scheduled content '{content.title}' on signage '{signage.name}'")
    return db_obj


@router.put("/schedules/{schedule_id}", response_model=SignageScheduleRead)
async def update_schedule(
    schedule_id: uuid.UUID,
    payload: SignageScheduleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_schedule(db, schedule_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jadwal tidak ditemukan")
    if payload.signage_id is not None:
        signage = await crud.get_signage(db, payload.signage_id)
        if signage is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signage tidak ditemukan")
    if payload.content_id is not None:
        content = await crud.get_content(db, payload.content_id)
        if content is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Konten signage tidak ditemukan")
    db_obj = await crud.update_schedule(db, db_obj, payload)
    await log_action(db, module="signage", action="update-schedule", user_id=current_user.id,
                     role=current_user.role.value, description=f"Updated signage schedule for content '{db_obj.content.title}'")
    return db_obj


@router.patch("/schedules/{schedule_id}/status", response_model=SignageScheduleRead)
async def update_schedule_status(
    schedule_id: uuid.UUID,
    payload: SignageScheduleStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_schedule(db, schedule_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jadwal tidak ditemukan")
    db_obj = await crud.update_schedule(db, db_obj, payload)
    await log_action(db, module="signage", action="update-schedule-status", user_id=current_user.id,
                     role=current_user.role.value,
                     description=f"Changed signage schedule active status to {db_obj.is_active}")
    return db_obj


@router.delete("/schedules/{schedule_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_schedule(
    schedule_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_schedule(db, schedule_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Jadwal tidak ditemukan")
    await log_action(db, module="signage", action="delete-schedule", user_id=current_user.id,
                     role=current_user.role.value,
                     description=f"Deleted signage schedule for content '{db_obj.content.title}'")
    await crud.delete_schedule(db, db_obj)
    return None


# ---------------------------------------------------------------------------
# Signage by ID (registered last to avoid shadowing sub-resources)
# ---------------------------------------------------------------------------
@router.get("/{signage_id}", response_model=SignageRead)
async def get_signage(signage_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_signage(db, signage_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signage tidak ditemukan")
    return db_obj


@router.put("/{signage_id}", response_model=SignageRead)
async def update_signage(
    signage_id: uuid.UUID,
    payload: SignageUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_signage(db, signage_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signage tidak ditemukan")
    if payload.code and payload.code != db_obj.code:
        existing = await crud.get_signage_by_code(db, payload.code)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Kode sudah digunakan")
    db_obj = await crud.update_signage(db, db_obj, payload)
    await log_action(db, module="signage", action="update", user_id=current_user.id,
                     role=current_user.role.value, description=f"Updated signage '{db_obj.name}' ({db_obj.code})")
    return db_obj


@router.patch("/{signage_id}/status", response_model=SignageRead)
async def update_signage_status(
    request: Request,
    signage_id: uuid.UUID,
    payload: SignageStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_signage(db, signage_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signage tidak ditemukan")
    db_obj = await crud.update_signage(db, db_obj, payload)
    await log_action(db, module="signage", action="update-status", user_id=current_user.id,
                     role=current_user.role.value, description=f"Changed signage '{db_obj.name}' status to {db_obj.status.value}")
    asyncio.create_task(_trigger_signage_sync(request))
    return db_obj


@router.delete("/{signage_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_signage(
    request: Request,
    signage_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin_or_teknisi),
):
    db_obj = await crud.get_signage(db, signage_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Signage tidak ditemukan")
    if await crud.is_signage_in_use(db, signage_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Signage sedang digunakan oleh penugasan atau jadwal",
        )
    await log_action(db, module="signage", action="delete", user_id=current_user.id,
                     role=current_user.role.value, description=f"Deleted signage '{db_obj.name}' ({db_obj.code})")
    await crud.delete_signage(db, db_obj)
    asyncio.create_task(_trigger_signage_sync(request))
    return None
