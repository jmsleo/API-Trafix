import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.devices import Device
from api_trafix.schemas.device import DeviceCreate, DeviceUpdate


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    device_type: str | None = None,
    gate_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Device], int]:
    stmt = select(Device)
    count_stmt = select(func.count()).select_from(Device)

    if search:
        like = f"%{search.strip()}%"
        condition = or_(Device.name.ilike(like), Device.ip_address.ilike(like))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if device_type:
        stmt = stmt.where(Device.type.ilike(f"%{device_type.strip()}%"))
        count_stmt = count_stmt.where(Device.type.ilike(f"%{device_type.strip()}%"))
    if gate_id is not None:
        stmt = stmt.where(Device.gate_id == gate_id)
        count_stmt = count_stmt.where(Device.gate_id == gate_id)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(Device.type, Device.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(db: AsyncSession, device_id: uuid.UUID) -> Device | None:
    result = await db.execute(select(Device).where(Device.id == device_id))
    return result.scalar_one_or_none()


async def get_by_gate(db: AsyncSession, gate_id: uuid.UUID) -> list[Device]:
    result = await db.execute(select(Device).where(Device.gate_id == gate_id))
    return list(result.scalars().all())


async def create(db: AsyncSession, payload: DeviceCreate) -> Device:
    db_obj = Device(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def update(db: AsyncSession, db_obj: Device, payload: DeviceUpdate) -> Device:
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


async def delete(db: AsyncSession, db_obj: Device) -> None:
    await db.delete(db_obj)
    await db.commit()
