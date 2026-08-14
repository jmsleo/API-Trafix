import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.models.member_vehicles import MemberVehicle
from api_trafix.models.park_transactions import ParkTransaction
from api_trafix.schemas.member_vehicle import MemberVehicleCreate, MemberVehicleUpdate


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    member_id: uuid.UUID | None = None,
    vehicle_type_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[MemberVehicle], int]:
    stmt = select(MemberVehicle).options(
        selectinload(MemberVehicle.member),
        selectinload(MemberVehicle.vehicle_type),
    )
    count_stmt = select(func.count()).select_from(MemberVehicle)

    if search:
        like = f"%{search.strip().upper()}%"
        stmt = stmt.where(MemberVehicle.police_number.ilike(like))
        count_stmt = count_stmt.where(MemberVehicle.police_number.ilike(like))
    if member_id is not None:
        stmt = stmt.where(MemberVehicle.member_id == member_id)
        count_stmt = count_stmt.where(MemberVehicle.member_id == member_id)
    if vehicle_type_id is not None:
        stmt = stmt.where(MemberVehicle.vehicle_type_id == vehicle_type_id)
        count_stmt = count_stmt.where(MemberVehicle.vehicle_type_id == vehicle_type_id)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(MemberVehicle.police_number)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(db: AsyncSession, vehicle_id: uuid.UUID) -> MemberVehicle | None:
    result = await db.execute(
        select(MemberVehicle)
        .where(MemberVehicle.id == vehicle_id)
        .options(
            selectinload(MemberVehicle.member),
            selectinload(MemberVehicle.vehicle_type),
        )
    )
    return result.scalar_one_or_none()


async def get_by_police_number(
    db: AsyncSession, police_number: str
) -> MemberVehicle | None:
    result = await db.execute(
        select(MemberVehicle).where(MemberVehicle.police_number == police_number.upper())
    )
    return result.scalar_one_or_none()


async def is_in_use(db: AsyncSession, vehicle_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(ParkTransaction)
        .where(ParkTransaction.member_vehicle_id == vehicle_id)
    )
    return (result.scalar_one() or 0) > 0


async def create(db: AsyncSession, payload: MemberVehicleCreate) -> MemberVehicle:
    db_obj = MemberVehicle(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    return await get_by_id(db, db_obj.id)


async def update(
    db: AsyncSession, db_obj: MemberVehicle, payload: MemberVehicleUpdate
) -> MemberVehicle:
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    obj_id = db_obj.id
    return await get_by_id(db, obj_id)


async def delete(db: AsyncSession, db_obj: MemberVehicle) -> None:
    await db.delete(db_obj)
    await db.commit()
