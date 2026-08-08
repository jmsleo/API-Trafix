import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.models.parking_rates import ParkingRate
from api_trafix.models.vehicle_types import VehicleType
from api_trafix.schemas.parking_rate import ParkingRateCreate, ParkingRateUpdate


async def get_all(db: AsyncSession) -> list[ParkingRate]:
    result = await db.execute(select(ParkingRate).order_by(ParkingRate.name))
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, parking_rate_id: uuid.UUID) -> ParkingRate | None:
    result = await db.execute(select(ParkingRate).where(ParkingRate.id == parking_rate_id))
    return result.scalar_one_or_none()


async def vehicle_type_exists(db: AsyncSession, vehicle_type_id: uuid.UUID) -> bool:
    result = await db.execute(select(VehicleType.id).where(VehicleType.id == vehicle_type_id))
    return result.scalar_one_or_none() is not None


async def create(db: AsyncSession, payload: ParkingRateCreate) -> ParkingRate:
    db_obj = ParkingRate(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def update(db: AsyncSession, db_obj: ParkingRate, payload: ParkingRateUpdate) -> ParkingRate:
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


async def delete(db: AsyncSession, db_obj: ParkingRate) -> None:
    await db.delete(db_obj)
    await db.commit()