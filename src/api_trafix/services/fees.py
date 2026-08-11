import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.parking_rates import ParkingRate, RateStatus


async def resolve_rate(
    db: AsyncSession, vehicle_type_id: uuid.UUID
) -> ParkingRate | None:
    result = await db.execute(
        select(ParkingRate)
        .where(
            ParkingRate.vehicle_type_id == vehicle_type_id,
            ParkingRate.status == RateStatus.ACTIVE,
        )
        .order_by(ParkingRate.created_at.desc())
    )
    return result.scalars().first()


async def calculate_fee(
    db: AsyncSession,
    vehicle_type_id: uuid.UUID,
    is_member: bool = False,
    member_subscription_active: bool = False,
) -> int:
    """Flat fee per vehicle type. Members with an active subscription park free."""
    if is_member and member_subscription_active:
        return 0
    rate = await resolve_rate(db, vehicle_type_id)
    return rate.base_price if rate is not None else 0
