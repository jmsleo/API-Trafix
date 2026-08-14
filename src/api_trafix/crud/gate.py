import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.gates import Gate, GateType
from api_trafix.models.park_transactions import ParkTransaction
from api_trafix.schemas.gate import GateCreate, GateUpdate


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    gate_type: GateType | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Gate], int]:
    stmt = select(Gate)
    count_stmt = select(func.count()).select_from(Gate)

    if search:
        like = f"%{search.strip()}%"
        condition = or_(Gate.name.ilike(like), Gate.gate_code.ilike(like))
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if gate_type is not None:
        stmt = stmt.where(Gate.type == gate_type)
        count_stmt = count_stmt.where(Gate.type == gate_type)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(Gate.gate_code, Gate.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(db: AsyncSession, gate_id: uuid.UUID) -> Gate | None:
    result = await db.execute(select(Gate).where(Gate.id == gate_id))
    return result.scalar_one_or_none()


async def get_by_gate_code(db: AsyncSession, gate_code: str) -> Gate | None:
    result = await db.execute(select(Gate).where(Gate.gate_code == gate_code))
    return result.scalar_one_or_none()


async def create(db: AsyncSession, payload: GateCreate) -> Gate:
    db_obj = Gate(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def update(db: AsyncSession, db_obj: Gate, payload: GateUpdate) -> Gate:
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


async def delete(db: AsyncSession, db_obj: Gate) -> None:
    await db.delete(db_obj)
    await db.commit()


async def is_in_use(db: AsyncSession, gate_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(ParkTransaction.id)
        .where(
            or_(
                ParkTransaction.entry_gate_id == gate_id,
                ParkTransaction.exit_gate_id == gate_id,
            )
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None
