import uuid
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.models.member_vehicles import MemberVehicle
from api_trafix.models.members import Member, MemberStatus
from api_trafix.schemas.member import MemberCreate, MemberUpdate


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    status: MemberStatus | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Member], int]:
    stmt = select(Member)
    count_stmt = select(func.count()).select_from(Member)

    if search:
        like = f"%{search.strip()}%"
        vehicle_match = exists().where(
            MemberVehicle.member_id == Member.id,
            MemberVehicle.police_number.ilike(like),
        )
        condition = or_(
            Member.member_code.ilike(like),
            Member.name.ilike(like),
            vehicle_match,
        )
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if status is not None:
        stmt = stmt.where(Member.status == status)
        count_stmt = count_stmt.where(Member.status == status)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(Member.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def block(db: AsyncSession, db_obj: Member) -> Member:
    db_obj.status = MemberStatus.BLOCKED
    await db.commit()
    await db.refresh(db_obj)
    return db_obj


async def get_by_id(db: AsyncSession, member_id: uuid.UUID) -> Member | None:
    result = await db.execute(select(Member).where(Member.id == member_id))
    return result.scalar_one_or_none()


async def get_by_member_code(db: AsyncSession, member_code: str) -> Member | None:
    result = await db.execute(select(Member).where(Member.member_code == member_code))
    return result.scalar_one_or_none()


async def create(db: AsyncSession, payload: MemberCreate) -> Member:
    db_obj = Member(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    await db.refresh(db_obj)
    return db_obj


async def update(db: AsyncSession, db_obj: Member, payload: MemberUpdate) -> Member:
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


async def delete(db: AsyncSession, db_obj: Member) -> None:
    await db.delete(db_obj)
    await db.commit()