import uuid
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.models.operator_shift_assignments import (
    OperatorShiftAssignment,
    OperatorShiftAssignmentStatus,
)
from api_trafix.schemas.operator_shift_assignment import (
    OperatorShiftAssignmentCreate,
    OperatorShiftAssignmentUpdate,
)


async def get_all(
    db: AsyncSession,
    operator_id: uuid.UUID | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[OperatorShiftAssignment], int]:
    stmt = select(OperatorShiftAssignment).options(
        selectinload(OperatorShiftAssignment.operator),
        selectinload(OperatorShiftAssignment.shift),
    )
    count_stmt = select(func.count()).select_from(OperatorShiftAssignment)

    if operator_id is not None:
        stmt = stmt.where(OperatorShiftAssignment.operator_id == operator_id)
        count_stmt = count_stmt.where(OperatorShiftAssignment.operator_id == operator_id)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(OperatorShiftAssignment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(
    db: AsyncSession, assignment_id: uuid.UUID
) -> OperatorShiftAssignment | None:
    result = await db.execute(
        select(OperatorShiftAssignment)
        .where(OperatorShiftAssignment.id == assignment_id)
        .options(
            selectinload(OperatorShiftAssignment.operator),
            selectinload(OperatorShiftAssignment.shift),
        )
    )
    return result.scalar_one_or_none()


async def get_by_operator_and_shift(
    db: AsyncSession, operator_id: uuid.UUID, shift_id: uuid.UUID
) -> OperatorShiftAssignment | None:
    result = await db.execute(
        select(OperatorShiftAssignment).where(
            OperatorShiftAssignment.operator_id == operator_id,
            OperatorShiftAssignment.shift_id == shift_id,
        )
    )
    return result.scalar_one_or_none()


async def get_active_by_operator(
    db: AsyncSession, operator_id: uuid.UUID
) -> list[OperatorShiftAssignment]:
    """Return the operator's ACTIVE shift assignments (with shift loaded)."""
    stmt = (
        select(OperatorShiftAssignment)
        .where(
            OperatorShiftAssignment.operator_id == operator_id,
            OperatorShiftAssignment.status == OperatorShiftAssignmentStatus.ACTIVE,
        )
        .options(selectinload(OperatorShiftAssignment.shift))
        .order_by(OperatorShiftAssignment.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def has_active_assignment(
    db: AsyncSession, operator_id: uuid.UUID, shift_id: uuid.UUID
) -> bool:
    """Whether the operator has an ACTIVE shift assignment for ``shift_id``."""
    result = await db.execute(
        select(OperatorShiftAssignment.id).where(
            OperatorShiftAssignment.operator_id == operator_id,
            OperatorShiftAssignment.shift_id == shift_id,
            OperatorShiftAssignment.status == OperatorShiftAssignmentStatus.ACTIVE,
        )
    )
    return result.scalar_one_or_none() is not None


async def get_by_shift_id(
    db: AsyncSession, shift_id: uuid.UUID, exclude_id: uuid.UUID | None = None
) -> OperatorShiftAssignment | None:
    stmt = select(OperatorShiftAssignment).where(
        OperatorShiftAssignment.shift_id == shift_id
    )
    if exclude_id is not None:
        stmt = stmt.where(OperatorShiftAssignment.id != exclude_id)
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession, payload: OperatorShiftAssignmentCreate
) -> OperatorShiftAssignment:
    db_obj = OperatorShiftAssignment(**payload.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return await get_by_id(db, db_obj.id)


async def update(
    db: AsyncSession,
    db_obj: OperatorShiftAssignment,
    payload: OperatorShiftAssignmentUpdate,
) -> OperatorShiftAssignment:
    data = payload.model_dump()
    for field, value in data.items():
        setattr(db_obj, field, value)
    await db.commit()
    await db.refresh(db_obj)
    return await get_by_id(db, db_obj.id)


async def delete(db: AsyncSession, db_obj: OperatorShiftAssignment) -> None:
    await db.delete(db_obj)
    await db.commit()
