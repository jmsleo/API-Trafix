import uuid
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.config.database import get_db
from api_trafix.crud import parking_rate_tier as crud
from api_trafix.schemas.parking_rate_tier import (
    ParkingRateTierCreate,
    ParkingRateTierRead,
    ParkingRateTierUpdate,
)

router = APIRouter(prefix="/parking-rate-tiers", tags=["Parking Rate Tiers"])


@router.get("/", response_model=list[ParkingRateTierRead])
async def list_parking_rate_tiers(
    parking_rate_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    if not await crud.parking_rate_exists(db, parking_rate_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Parking rate not found"
        )
    return await crud.get_all_by_rate_id(db, parking_rate_id)


@router.get("/{tier_id}", response_model=ParkingRateTierRead)
async def get_parking_rate_tier(tier_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, tier_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking rate tier not found")
    return db_obj


@router.post("/", response_model=ParkingRateTierRead, status_code=status.HTTP_201_CREATED)
async def create_parking_rate_tier(
    payload: ParkingRateTierCreate, db: AsyncSession = Depends(get_db)
):
    if not await crud.parking_rate_exists(db, payload.parking_rate_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="parking_rate_id does not refer to an existing parking rate",
        )
    try:
        return await crud.create(db, payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid parking_rate_id or constraint violation",
        )


@router.put("/{tier_id}", response_model=ParkingRateTierRead)
async def update_parking_rate_tier(
    tier_id: uuid.UUID,
    payload: ParkingRateTierUpdate,
    db: AsyncSession = Depends(get_db),
):
    db_obj = await crud.get_by_id(db, tier_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking rate tier not found")

    if payload.parking_rate_id is not None:
        if not await crud.parking_rate_exists(db, payload.parking_rate_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="parking_rate_id does not refer to an existing parking rate",
            )

    try:
        return await crud.update(db, db_obj, payload)
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid parking_rate_id or constraint violation",
        )


@router.delete("/{tier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_parking_rate_tier(tier_id: uuid.UUID, db: AsyncSession = Depends(get_db)):
    db_obj = await crud.get_by_id(db, tier_id)
    if db_obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Parking rate tier not found")
    await crud.delete(db, db_obj)
    return None