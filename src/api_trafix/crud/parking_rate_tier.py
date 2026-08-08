import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.models.parking_rate_tiers import ParkingRateTier
from api_trafix.models.parking_rates import ParkingRate
from api_trafix.schemas.parking_rate_tier import (
    ParkingRateTierCreate,
    ParkingRateTierUpdate,
)


async def get_all_by_rate_id(
    db: AsyncSession, parking_rate_id: uuid.UUID
) -> list[ParkingRateTier]:
    result = await db.execute(
        select(ParkingRateTier)
        .where(ParkingRateTier.parking_rate_id == parking_rate_id)
        .order_by(ParkingRateTier.tier_order)
    )
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, tier_id: uuid.UUID) -> ParkingRateTier | None:
    result = await db.execute(
        select(ParkingRateTier).where(ParkingRateTier.id == tier_id)
    )
    return result.scalar_one_or_none()


async def parking_rate_exists(db: AsyncSession, parking_rate_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ParkingRate.id).where(ParkingRate.id == parking_rate_id)
    )
    return result.scalar_one_or_none() is not None


async def create(db: AsyncSession, payload: ParkingRateTierCreate) -> ParkingRateTier:
    db_obj = ParkingRateTier(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def update(
    db: AsyncSession, db_obj: ParkingRateTier, payload: ParkingRateTierUpdate
) -> ParkingRateTier:
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def delete(db: AsyncSession, db_obj: ParkingRateTier) -> None:
    await db.delete(db_obj)
    await db.commit()