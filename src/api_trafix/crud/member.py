import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from api_trafix.models.members import Member
from api_trafix.schemas.member import MemberCreate, MemberUpdate


async def get_all(db: AsyncSession) -> list[Member]:
    result = await db.execute(select(Member).order_by(Member.name))
    return list(result.scalars().all())


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