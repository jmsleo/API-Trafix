import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.models.member_subscriptions import MemberSubscription
from api_trafix.models.subscription_plans import SubscriptionPlan
from api_trafix.models.vehicle_types import VehicleType
from api_trafix.schemas.subscription_plan import SubscriptionPlanCreate, SubscriptionPlanUpdate


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    is_active: bool | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[SubscriptionPlan], int]:
    stmt = select(SubscriptionPlan)
    count_stmt = select(func.count()).select_from(SubscriptionPlan)

    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(SubscriptionPlan.name.ilike(like))
        count_stmt = count_stmt.where(SubscriptionPlan.name.ilike(like))
    if is_active is not None:
        stmt = stmt.where(SubscriptionPlan.is_active == is_active)
        count_stmt = count_stmt.where(SubscriptionPlan.is_active == is_active)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.options(selectinload(SubscriptionPlan.vehicle_type))
        .order_by(SubscriptionPlan.name)
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(db: AsyncSession, plan_id: uuid.UUID) -> SubscriptionPlan | None:
    result = await db.execute(
        select(SubscriptionPlan)
        .where(SubscriptionPlan.id == plan_id)
        .options(selectinload(SubscriptionPlan.vehicle_type))
    )
    return result.scalar_one_or_none()


async def vehicle_type_exists(db: AsyncSession, vehicle_type_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(func.count()).select_from(VehicleType).where(VehicleType.id == vehicle_type_id)
    )
    return (result.scalar_one() or 0) > 0


async def get_by_name(db: AsyncSession, name: str) -> SubscriptionPlan | None:
    result = await db.execute(select(SubscriptionPlan).where(SubscriptionPlan.name == name))
    return result.scalar_one_or_none()


async def is_in_use(db: AsyncSession, plan_id: uuid.UUID) -> bool:
    result = await db.execute(
        select(func.count()).select_from(MemberSubscription).where(
            MemberSubscription.plan_id == plan_id
        )
    )
    return (result.scalar_one() or 0) > 0


async def create(db: AsyncSession, payload: SubscriptionPlanCreate) -> SubscriptionPlan:
    db_obj = SubscriptionPlan(**payload.model_dump())
    db.add(db_obj)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    return await get_by_id(db, db_obj.id)


async def update(
    db: AsyncSession, db_obj: SubscriptionPlan, payload: SubscriptionPlanUpdate
) -> SubscriptionPlan:
    update_data = payload.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(db_obj, field, value)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise
    return await get_by_id(db, db_obj.id)


async def delete(db: AsyncSession, db_obj: SubscriptionPlan) -> None:
    await db.delete(db_obj)
    await db.commit()
