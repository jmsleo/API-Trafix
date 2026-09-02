import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.models.parking_rates import ParkingRate, RateStatus
from api_trafix.models.vehicle_types import VehicleType
from api_trafix.schemas.parking_rate import ParkingRateCreate, ParkingRateUpdate


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    status: RateStatus | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[ParkingRate], int]:
    stmt = select(ParkingRate)
    count_stmt = select(func.count()).select_from(ParkingRate)

    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(ParkingRate.name.ilike(like))
        count_stmt = count_stmt.where(ParkingRate.name.ilike(like))
    if status is not None:
        stmt = stmt.where(ParkingRate.status == status)
        count_stmt = count_stmt.where(ParkingRate.status == status)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(ParkingRate.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(db: AsyncSession, parking_rate_id: uuid.UUID) -> ParkingRate | None:
    result = await db.execute(select(ParkingRate).where(ParkingRate.id == parking_rate_id))
    return result.scalar_one_or_none()


async def get_by_name(db: AsyncSession, name: str) -> ParkingRate | None:
    result = await db.execute(
        select(ParkingRate).where(func.lower(ParkingRate.name) == name.strip().lower())
    )
    return result.scalar_one_or_none()


async def update_status(
    db: AsyncSession, db_obj: ParkingRate, status: RateStatus
) -> ParkingRate:
    db_obj.status = status
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


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