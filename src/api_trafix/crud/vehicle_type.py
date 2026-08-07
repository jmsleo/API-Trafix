import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.models.vehicle_types import VehicleType
from api_trafix.schemas.vehicle_type import VehicleTypeCreate, VehicleTypeUpdate


async def get_all(db: AsyncSession) -> list[VehicleType]:
    result = await db.execute(select(VehicleType).order_by(VehicleType.name))
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, vehicle_type_id: uuid.UUID) -> VehicleType | None:
    result = await db.execute(
        select(VehicleType).where(VehicleType.id == vehicle_type_id)
    )
    return result.scalar_one_or_none()


async def get_by_code(db: AsyncSession, code: str) -> VehicleType | None:
    result = await db.execute(select(VehicleType).where(VehicleType.code == code))
    return result.scalar_one_or_none()


async def create(db: AsyncSession, payload: VehicleTypeCreate) -> VehicleType:
    db_obj = VehicleType(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def update(
    db: AsyncSession, db_obj: VehicleType, payload: VehicleTypeUpdate
) -> VehicleType:
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


async def delete(db: AsyncSession, db_obj: VehicleType) -> None:
    await db.delete(db_obj)
    await db.commit()