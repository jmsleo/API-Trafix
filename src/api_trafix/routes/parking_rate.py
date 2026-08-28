import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.config.database import get_db
from api_trafix.core.dependencies import get_current_admin
from api_trafix.crud import parking_rate as crud
from api_trafix.models import RateStatus, User
from api_trafix.schemas.parking_rate import (
    ParkingRateCreate,
    ParkingRatePage,
    ParkingRateRead,
    ParkingRateStatusUpdate,
    ParkingRateUpdate,
)
from api_trafix.services.audit import log_action

router = APIRouter(prefix="/parking-rates", tags=["Parking Rates"])


@router.get("/", response_model=ParkingRatePage)
async def list_parking_rates(
    search: str | None = Query(default=None, max_length=100),
    status_filter: RateStatus | None = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=10, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    items, total = await crud.get_all(
        db, search=search, status=status_filter, page=page, page_size=page_size
    )
    total_pages = (total + page_size - 1) // page_size
    return ParkingRatePage(
        items=items, total=total, page=page, page_size=page_size, total_pages=total_pages
    )


@router.get("/{parking_rate_id}", response_model=ParkingRateRead)
async def get_parking_rate(
    parking_rate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, parking_rate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarif parkir tidak ditemukan")
    return db_obj


@router.post("/", response_model=ParkingRateRead, status_code=status.HTTP_201_CREATED)
async def create_parking_rate(
    payload: ParkingRateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    if not await crud.vehicle_type_exists(db, payload.vehicle_type_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="vehicle_type_id tidak merujuk ke jenis kendaraan yang ada",
        )
    try:
        db_obj = await crud.create(db, payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="vehicle_type_id tidak valid atau melanggar batasan",
        )
    await log_action(
        db,
        module="parking-rate",
        action="create",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Created parking rate '{db_obj.name}'",
    )
    return db_obj


@router.put("/{parking_rate_id}", response_model=ParkingRateRead)
async def update_parking_rate(
    parking_rate_id: uuid.UUID,
    payload: ParkingRateUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, parking_rate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarif parkir tidak ditemukan")

    if payload.vehicle_type_id is not None:
        if not await crud.vehicle_type_exists(db, payload.vehicle_type_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="vehicle_type_id tidak merujuk ke jenis kendaraan yang ada",
            )

    try:
        db_obj = await crud.update(db, db_obj, payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="vehicle_type_id tidak valid atau melanggar batasan",
        )
    await log_action(
        db,
        module="parking-rate",
        action="update",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Updated parking rate '{db_obj.name}'",
    )
    return db_obj


@router.patch("/{parking_rate_id}/status", response_model=ParkingRateRead)
async def update_parking_rate_status(
    parking_rate_id: uuid.UUID,
    payload: ParkingRateStatusUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, parking_rate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarif parkir tidak ditemukan")
    db_obj = await crud.update_status(db, db_obj, payload.status)
    await log_action(
        db,
        module="parking-rate",
        action="status",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Changed parking rate '{db_obj.name}' status to {payload.status}",
    )
    return db_obj


@router.delete("/{parking_rate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_parking_rate(
    parking_rate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_admin),
):
    db_obj = await crud.get_by_id(db, parking_rate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarif parkir tidak ditemukan")
    await log_action(
        db,
        module="parking-rate",
        action="delete",
        user_id=current_user.id,
        role=current_user.role.value,
        description=f"Deleted parking rate '{db_obj.name}'",
    )
    await crud.delete(db, db_obj)
    return None