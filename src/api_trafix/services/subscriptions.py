from datetime import datetime, timezone

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.member_subscriptions import (
    MemberSubscription,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
)


async def auto_expire(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    result = await db.execute(
        update(MemberSubscription)
        .where(
            MemberSubscription.status == STATUS_ACTIVE,
            MemberSubscription.end_date < now,
        )
        .values(status=STATUS_EXPIRED)
    )
    await db.commit()
    return result.rowcount or 0
