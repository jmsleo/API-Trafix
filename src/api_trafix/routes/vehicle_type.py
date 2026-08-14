import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import vehicle_type as crud
from api_trafix.models import User, VehicleStatus
from api_trafix.schemas.vehicle_type import (
    VehicleTypeCreate,
    VehicleTypePage,
    VehicleTypeRead,
    VehicleTypeUpdate,
)
from api_trafix.services.audit import log_action

router = APIRouter(prefix="/vehicle-types", tags=["Vehicle Types"])


@router.get("/", response_model=VehicleTypePage)
async def list_vehicle_types(
    search: str | None = Query(default=None, max_length=100),
    status_filter: VehicleStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    items, total = await crud.get_all(
        db, search=search, status=status_filter, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return VehicleTypePage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{vehicle_type_id}", response_model=VehicleTypeRead)
async def get_vehicle_type(
    vehicle_type_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, vehicle_type_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle type not found")
    return db_obj


@router.post("/", response_model=VehicleTypeRead, status_code=status.HTTP_201_CREATED)
async def create_vehicle_type(
    payload: VehicleTypeCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    existing = await crud.get_by_code(db, payload.code)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code already exists")
    db_obj = await crud.create(db, payload)
    await log_action(
        db,
        module="vehicle-type",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Created vehicle type '{db_obj.name}' ({db_obj.code})",
    )
    return db_obj


@router.put("/{vehicle_type_id}", response_model=VehicleTypeRead)
async def update_vehicle_type(
    vehicle_type_id: uuid.UUID,
    payload: VehicleTypeUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, vehicle_type_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle type not found")

    if payload.code and payload.code != db_obj.code:
        existing = await crud.get_by_code(db, payload.code)
        if existing is not None:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Code already exists")

    db_obj = await crud.update(db, db_obj, payload)
    await log_action(
        db,
        module="vehicle-type",
        action="update",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Updated vehicle type '{db_obj.name}' ({db_obj.code})",
    )
    return db_obj


@router.delete("/{vehicle_type_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vehicle_type(
    vehicle_type_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, vehicle_type_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Vehicle type not found")
    if await crud.is_in_use(db, vehicle_type_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Vehicle type is used by parking rates or member vehicles",
        )
    await log_action(
        db,
        module="vehicle-type",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Deleted vehicle type '{db_obj.name}' ({db_obj.code})",
    )
    await crud.delete(db, db_obj)
    return None
