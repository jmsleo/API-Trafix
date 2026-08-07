import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.config.database import get_db
from api_trafix.crud import parking_rate as crud
from api_trafix.schemas.parking_rate import (
    ParkingRateCreate,
    ParkingRateRead,
    ParkingRateUpdate,
)

router = APIRouter(prefix="/parking-rates", tags=["Parking Rates"])


@router.get("/", response_model=list[ParkingRateRead])
async def list_parking_rates(db: AsyncSession = Depends(get_db)):
    return await crud.get_all(db)


@router.get("/{parking_rate_id}", response_model=ParkingRateRead)
async def get_parking_rate(parking_rate_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, parking_rate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking rate not found")
    return db_obj


@router.post("/", response_model=ParkingRateRead, status_code=status.HTTP_201_CREATED)
async def create_parking_rate(payload: ParkingRateCreate, db: AsyncSession = Depends(get_db)):
    if not await crud.vehicle_type_exists(db, payload.vehicle_type_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="vehicle_type_id does not refer to an existing vehicle type",
        )
    try:
        return await crud.create(db, payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid vehicle_type_id or constraint violation",
        )


@router.put("/{parking_rate_id}", response_model=ParkingRateRead)
async def update_parking_rate(
    parking_rate_id: uuid.UUID,
    payload: ParkingRateUpdate,
    db: AsyncSession = Depends(get_db),
):
    db_obj = await crud.get_by_id(db, parking_rate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking rate not found")

    if payload.vehicle_type_id is not None:
        if not await crud.vehicle_type_exists(db, payload.vehicle_type_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="vehicle_type_id does not refer to an existing vehicle type",
            )

    try:
        return await crud.update(db, db_obj, payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid vehicle_type_id or constraint violation",
        )


@router.delete("/{parking_rate_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_parking_rate(parking_rate_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, parking_rate_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking rate not found")
    await crud.delete(db, db_obj)
    return None