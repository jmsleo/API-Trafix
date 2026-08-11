import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import audit_log as crud
from api_trafix.models import User
from api_trafix.schemas.audit_log import AuditLogPage, AuditLogRead

router = APIRouter(prefix="/audit-logs", tags=["Audit Log"])


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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Audit log not found")
    return db_obj
