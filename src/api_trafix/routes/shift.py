import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import shift as crud
from api_trafix.models import ShiftStatus, User
from api_trafix.schemas.shift import ShiftCreate, ShiftPage, ShiftRead, ShiftUpdate
from api_trafix.services.audit import log_action

router = APIRouter(prefix="/shifts", tags=["Shifts"])


@router.get("/", response_model=ShiftPage)
async def list_shifts(
    search: str | None = Query(default=None, max_length=100),
    status_filter: ShiftStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    items, total = await crud.get_all(
        db, search=search, status=status_filter, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return ShiftPage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{shift_id}", response_model=ShiftRead)
async def get_shift(
    shift_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, shift_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
    return db_obj


@router.post("/", response_model=ShiftRead, status_code=status.HTTP_201_CREATED)
async def create_shift(
    payload: ShiftCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    existing = await crud.get_by_name(db, payload.name)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name already exists")
    db_obj = await crud.create(db, payload)
    await log_action(
        db,
        module="shift",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Created shift '{db_obj.name}'",
    )
    return db_obj


@router.put("/{shift_id}", response_model=ShiftRead)
async def update_shift(
    shift_id: uuid.UUID,
    payload: ShiftUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, shift_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")

    if payload.name and payload.name != db_obj.name:
        existing = await crud.get_by_name(db, payload.name)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Name already exists")

    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        module="shift",
        action="update",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Updated shift '{db_obj.name}'",
    )
    return db_obj


@router.delete("/{shift_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_shift(
    shift_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, shift_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Shift not found")
    await log_action(
        db,
        module="shift",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Deleted shift '{db_obj.name}'",
    )
    await crud.delete(db, db_obj)
    return None
