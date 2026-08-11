import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.models import (
    Signage,
    SignageAssignment,
    SignageContent,
    SignageContentType,
    SignageSchedule,
    SignageStatus,
)
from api_trafix.schemas.signage import (
    SignageAssignmentCreate,
    SignageContentCreate,
    SignageContentUpdate,
    SignageCreate,
    SignageScheduleCreate,
    SignageScheduleUpdate,
    SignageUpdate,
)

_ASSIGNMENT_LOAD = (
    selectinload(SignageAssignment.signage),
    selectinload(SignageAssignment.content),
)

_SCHEDULE_LOAD = (
    selectinload(SignageSchedule.signage),
    selectinload(SignageSchedule.content),
)


# ---------------------------------------------------------------------------
# Signage
# ---------------------------------------------------------------------------
async def get_all_signages(
    db: AsyncSession,
    search: str | None = None,
    status: SignageStatus | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Signage], int]:
    stmt = select(Signage)
    count_stmt = select(func.count()).select_from(Signage)

    if search:
        like = f"%{search.strip()}%"
        condition = Signage.name.ilike(like) | Signage.code.ilike(like)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if status is not None:
        stmt = stmt.where(Signage.status == status)
        count_stmt = count_stmt.where(Signage.status == status)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(Signage.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_signage(db: AsyncSession, signage_id: uuid.UUID) -> Signage | None:
    result = await db.execute(select(Signage).where(Signage.id == signage_id))
    return result.scalar_one_or_none()


async def get_signage_by_code(db: AsyncSession, code: str) -> Signage | None:
    result = await db.execute(select(Signage).where(Signage.code == code))
    return result.scalar_one_or_none()


async def is_signage_in_use(db: AsyncSession, signage_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(SignageAssignment)
        .where(SignageAssignment.signage_id == signage_id)
    )
    assignments = result.scalar_one() or 0
    result = await db.execute(
        select(func.count())
        .select_from(SignageSchedule)
        .where(SignageSchedule.signage_id == signage_id)
    )
    schedules = result.scalar_one() or 0
    return (assignments + schedules) > 0


async def create_signage(db: AsyncSession, payload: SignageCreate) -> Signage:
    db_obj = Signage(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def update_signage(
    db: AsyncSession, db_obj: Signage, payload: SignageUpdate
) -> Signage:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(db_obj, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def delete_signage(db: AsyncSession, db_obj: Signage) -> None:
    await db.delete(db_obj)
    await db.commit()


# ---------------------------------------------------------------------------
# Signage Content
# ---------------------------------------------------------------------------
async def get_all_contents(
    db: AsyncSession,
    search: str | None = None,
    content_type: SignageContentType | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[SignageContent], int]:
    stmt = select(SignageContent)
    count_stmt = select(func.count()).select_from(SignageContent)

    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(SignageContent.title.ilike(like))
        count_stmt = count_stmt.where(SignageContent.title.ilike(like))
    if content_type is not None:
        stmt = stmt.where(SignageContent.content_type == content_type)
        count_stmt = count_stmt.where(SignageContent.content_type == content_type)
    if is_active is not None:
        stmt = stmt.where(SignageContent.is_active == is_active)
        count_stmt = count_stmt.where(SignageContent.is_active == is_active)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(SignageContent.title)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_content(db: AsyncSession, content_id: uuid.UUID) -> SignageContent | None:
    result = await db.execute(select(SignageContent).where(SignageContent.id == content_id))
    return result.scalar_one_or_none()


async def is_content_in_use(db: AsyncSession, content_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(func.count())
        .select_from(SignageAssignment)
        .where(SignageAssignment.content_id == content_id)
    )
    assignments = result.scalar_one() or 0
    result = await db.execute(
        select(func.count())
        .select_from(SignageSchedule)
        .where(SignageSchedule.content_id == content_id)
    )
    schedules = result.scalar_one() or 0
    return (assignments + schedules) > 0


async def create_content(db: AsyncSession, payload: SignageContentCreate) -> SignageContent:
    db_obj = SignageContent(**payload.model_dump())
    db.add(db_obj)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def update_content(
    db: AsyncSession, db_obj: SignageContent, payload: SignageContentUpdate
) -> SignageContent:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(db_obj, field, value)
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def delete_content(db: AsyncSession, db_obj: SignageContent) -> None:
    await db.delete(db_obj)
    await db.commit()


# ---------------------------------------------------------------------------
# Content Assignment
# ---------------------------------------------------------------------------
async def get_all_assignments(
    db: AsyncSession,
    signage_id: uuid.UUID | None = None,
    content_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[SignageAssignment], int]:
    stmt = select(SignageAssignment)
    count_stmt = select(func.count()).select_from(SignageAssignment)

    if signage_id is not None:
        stmt = stmt.where(SignageAssignment.signage_id == signage_id)
        count_stmt = count_stmt.where(SignageAssignment.signage_id == signage_id)
    if content_id is not None:
        stmt = stmt.where(SignageAssignment.content_id == content_id)
        count_stmt = count_stmt.where(SignageAssignment.content_id == content_id)
    if is_active is not None:
        stmt = stmt.where(SignageAssignment.is_active == is_active)
        count_stmt = count_stmt.where(SignageAssignment.is_active == is_active)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.options(*_ASSIGNMENT_LOAD)
        .order_by(SignageAssignment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_assignment(
    db: AsyncSession, assignment_id: uuid.UUID
) -> SignageAssignment | None:
    result = await db.execute(
        select(SignageAssignment)
        .where(SignageAssignment.id == assignment_id)
        .options(*_ASSIGNMENT_LOAD)
    )
    return result.scalar_one_or_none()


async def get_assignment_by_pair(
    db: AsyncSession, signage_id: uuid.UUID, content_id: uuid.UUID
) -> SignageAssignment | None:
    result = await db.execute(
        select(SignageAssignment).where(
            SignageAssignment.signage_id == signage_id,
            SignageAssignment.content_id == content_id,
        )
    )
    return result.scalar_one_or_none()


async def create_assignment(
    db: AsyncSession, payload: SignageAssignmentCreate
) -> SignageAssignment:
    db_obj = SignageAssignment(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    return await get_assignment(db, db_obj.id)


async def update_assignment(
    db: AsyncSession, db_obj: SignageAssignment, payload
) -> SignageAssignment:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(db_obj, field, value)
    await db.commit()
    return await get_assignment(db, db_obj.id)


async def delete_assignment(db: AsyncSession, db_obj: SignageAssignment) -> None:
    await db.delete(db_obj)
    await db.commit()


# ---------------------------------------------------------------------------
# Content Scheduling
# ---------------------------------------------------------------------------
async def get_all_schedules(
    db: AsyncSession,
    signage_id: uuid.UUID | None = None,
    content_id: uuid.UUID | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[SignageSchedule], int]:
    stmt = select(SignageSchedule)
    count_stmt = select(func.count()).select_from(SignageSchedule)

    if signage_id is not None:
        stmt = stmt.where(SignageSchedule.signage_id == signage_id)
        count_stmt = count_stmt.where(SignageSchedule.signage_id == signage_id)
    if content_id is not None:
        stmt = stmt.where(SignageSchedule.content_id == content_id)
        count_stmt = count_stmt.where(SignageSchedule.content_id == content_id)
    if is_active is not None:
        stmt = stmt.where(SignageSchedule.is_active == is_active)
        count_stmt = count_stmt.where(SignageSchedule.is_active == is_active)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.options(*_SCHEDULE_LOAD)
        .order_by(SignageSchedule.start_time)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_schedule(db: AsyncSession, schedule_id: uuid.UUID) -> SignageSchedule | None:
    result = await db.execute(
        select(SignageSchedule)
        .where(SignageSchedule.id == schedule_id)
        .options(*_SCHEDULE_LOAD)
    )
    return result.scalar_one_or_none()


async def create_schedule(
    db: AsyncSession, payload: SignageScheduleCreate
) -> SignageSchedule:
    db_obj = SignageSchedule(**payload.model_dump())
    db.add(db_obj)
    await db.commit()
    return await get_schedule(db, db_obj.id)


async def update_schedule(
    db: AsyncSession, db_obj: SignageSchedule, payload: SignageScheduleUpdate
) -> SignageSchedule:
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(db_obj, field, value)
    await db.commit()
    return await get_schedule(db, db_obj.id)


async def delete_schedule(db: AsyncSession, db_obj: SignageSchedule) -> None:
    await db.delete(db_obj)
    await db.commit()
