import uuid
from datetime import datetime, timedelta, timezone
from sqlalchemy import exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from api_trafix.models.member_subscriptions import MemberSubscription, STATUS_ACTIVE
from api_trafix.models.member_vehicles import MemberVehicle
from api_trafix.models.members import Member, MemberStatus
from api_trafix.models.subscription_plans import SubscriptionPlan
from api_trafix.schemas.member import MemberCreate, MemberUpdate
from api_trafix.utils.codes import generate_member_code


def _with_children(stmt):
    return stmt.options(
        selectinload(Member.vehicles).selectinload(MemberVehicle.vehicle_type),
        selectinload(Member.subscriptions).selectinload(MemberSubscription.plan),
    )


async def _unique_member_code(db: AsyncSession) -> str:
    for _ in range(10):
        code = generate_member_code()
        if await get_by_member_code(db, code) is None:
            return code
    raise IntegrityError("Could not generate a unique member code", None, None)


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    status: MemberStatus | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Member], int]:
    stmt = _with_children(select(Member))
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
    db_obj = await get_by_id(db, db_obj.id)
    assert db_obj is not None
    return db_obj


async def get_by_id(db: AsyncSession, member_id: uuid.UUID) -> Member | None:
    result = await db.execute(
        _with_children(select(Member)).where(Member.id == member_id)
    )
    return result.scalar_one_or_none()


async def get_by_member_code(db: AsyncSession, member_code: str) -> Member | None:
    result = await db.execute(select(Member).where(Member.member_code == member_code))
    return result.scalar_one_or_none()


async def get_by_card_number(db: AsyncSession, card_number: str) -> Member | None:
    result = await db.execute(select(Member).where(Member.card_number == card_number))
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    payload: MemberCreate,
    plan: SubscriptionPlan | None = None,
) -> Member:
    member_data = payload.model_dump(exclude={"police_number", "vehicle_type_id", "plan_id"})
    for _ in range(5):
        db_obj = Member(**member_data, member_code=await _unique_member_code(db))
        db.add(db_obj)
        try:
            await db.flush()
        except IntegrityError:
            await db.rollback()
            continue
        if payload.police_number is not None and payload.vehicle_type_id is not None:
            db.add(
                MemberVehicle(
                    member_id=db_obj.id,
                    vehicle_type_id=payload.vehicle_type_id,
                    police_number=payload.police_number,
                )
            )
        if plan is not None:
            start_date = datetime.now(timezone.utc)
            db.add(
                MemberSubscription(
                    member_id=db_obj.id,
                    plan_id=plan.id,
                    start_date=start_date,
                    end_date=start_date + timedelta(days=plan.duration_in_days),
                    status=STATUS_ACTIVE,
                )
            )
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            raise
        db_obj = await get_by_id(db, db_obj.id)
        assert db_obj is not None
        return db_obj
    raise IntegrityError("Could not generate a unique member code", None, None)


async def police_number_exists(db: AsyncSession, police_number: str) -> bool:
    result = await db.execute(
        select(MemberVehicle.id)
        .where(MemberVehicle.police_number == police_number)
        .limit(1)
    )
    return result.scalar_one_or_none() is not None


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
    db_obj = await get_by_id(db, db_obj.id)
    assert db_obj is not None
    return db_obj


async def delete(db: AsyncSession, db_obj: Member) -> None:
    await db.delete(db_obj)
    await db.commit()