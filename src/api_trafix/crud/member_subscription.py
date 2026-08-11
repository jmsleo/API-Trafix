import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.models.member_subscriptions import (
    MemberSubscription,
    STATUS_ACTIVE,
    STATUS_CANCELLED,
)
from api_trafix.models.subscription_plans import SubscriptionPlan
from api_trafix.schemas.member_subscription import MemberSubscriptionCreate


async def get_all(
    db: AsyncSession,
    member_id: uuid.UUID | None = None,
    plan_id: uuid.UUID | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[MemberSubscription], int]:
    stmt = select(MemberSubscription).options(
        selectinload(MemberSubscription.member),
        selectinload(MemberSubscription.plan),
    )
    count_stmt = select(func.count()).select_from(MemberSubscription)

    if member_id is not None:
        stmt = stmt.where(MemberSubscription.member_id == member_id)
        count_stmt = count_stmt.where(MemberSubscription.member_id == member_id)
    if plan_id is not None:
        stmt = stmt.where(MemberSubscription.plan_id == plan_id)
        count_stmt = count_stmt.where(MemberSubscription.plan_id == plan_id)
    if status is not None:
        stmt = stmt.where(MemberSubscription.status == status)
        count_stmt = count_stmt.where(MemberSubscription.status == status)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(MemberSubscription.start_date.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(
    db: AsyncSession, subscription_id: uuid.UUID
) -> MemberSubscription | None:
    result = await db.execute(
        select(MemberSubscription)
        .where(MemberSubscription.id == subscription_id)
        .options(
            selectinload(MemberSubscription.member),
            selectinload(MemberSubscription.plan),
        )
    )
    return result.scalar_one_or_none()


async def get_active_for_member(
    db: AsyncSession, member_id: uuid.UUID
) -> MemberSubscription | None:
    result = await db.execute(
        select(MemberSubscription).where(
            MemberSubscription.member_id == member_id,
            MemberSubscription.status == STATUS_ACTIVE,
        )
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    payload: MemberSubscriptionCreate,
    plan: SubscriptionPlan,
) -> MemberSubscription:
    start_date = payload.start_date or datetime.now(timezone.utc)
    if start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    end_date = start_date + timedelta(days=plan.duration_in_days)

    db_obj = MemberSubscription(
        member_id=payload.member_id,
        plan_id=payload.plan_id,
        start_date=start_date,
        end_date=end_date,
        status=STATUS_ACTIVE,
    )
    db.add(db_obj)
    await db.commit()
    return await get_by_id(db, db_obj.id)


async def cancel(db: AsyncSession, db_obj: MemberSubscription) -> MemberSubscription:
    db_obj.status = STATUS_CANCELLED
    await db.commit()
    return await get_by_id(db, db_obj.id)


async def delete(db: AsyncSession, db_obj: MemberSubscription) -> None:
    await db.delete(db_obj)
    await db.commit()
