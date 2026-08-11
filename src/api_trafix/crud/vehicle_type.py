import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.models.vehicle_types import VehicleStatus, VehicleType
from api_trafix.schemas.vehicle_type import VehicleTypeCreate, VehicleTypeUpdate


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    status: VehicleStatus | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[VehicleType], int]:
    stmt = select(VehicleType)
    count_stmt = select(func.count()).select_from(VehicleType)

    if search:
        like = f"%{search.strip()}%"
        condition = or_(VehicleType.name.ilike(like), VehicleType.code.ilike(like))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if status is not None:
        stmt = stmt.where(VehicleType.status == status)
        count_stmt = count_stmt.where(VehicleType.status == status)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(VehicleType.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


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