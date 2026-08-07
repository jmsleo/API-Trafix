import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.models.shifts import Shift
from api_trafix.schemas.shift import ShiftCreate, ShiftUpdate


async def get_all(db: AsyncSession) -> list[Shift]:
    result = await db.execute(select(Shift).order_by(Shift.name))
    return list(result.scalars().all())


async def get_by_id(db: AsyncSession, shift_id: uuid.UUID) -> Shift | None:
    result = await db.execute(select(Shift).where(Shift.id == shift_id))
    return result.scalar_one_or_none()


async def get_by_name(db: AsyncSession, name: str) -> Shift | None:
    result = await db.execute(select(Shift).where(Shift.name == name))
    return result.scalar_one_or_none()


async def create(db: AsyncSession, payload: ShiftCreate) -> Shift:
    db_obj = Shift(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def update(db: AsyncSession, db_obj: Shift, payload: ShiftUpdate) -> Shift:
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


async def delete(db: AsyncSession, db_obj: Shift) -> None:
    await db.delete(db_obj)
    await db.commit()