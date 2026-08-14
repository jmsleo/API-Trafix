from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.signage import SignageContent


async def sync_broadcast_windows(db: AsyncSession) -> int:
    now = datetime.now(UTC)
    changed = 0

    windowed = (
        await db.execute(
            select(SignageContent.id, SignageContent.broadcast_start, SignageContent.broadcast_end)
            .where(
                SignageContent.broadcast_start.isnot(None)
                | SignageContent.broadcast_end.isnot(None)
            )
        )
    ).all()

    activate: list = []
    deactivate: list = []
    for row in windowed:
        content_id, start, end = row
        if start is not None and now < start or end is not None and now >= end:
            deactivate.append(content_id)
        else:
            activate.append(content_id)

    if activate:
        result = await db.execute(
            update(SignageContent)
            .where(SignageContent.id.in_(activate), SignageContent.is_active.is_(False))
            .values(is_active=True)
        )
        changed += result.rowcount or 0
    if deactivate:
        result = await db.execute(
            update(SignageContent)
            .where(SignageContent.id.in_(deactivate), SignageContent.is_active.is_(True))
            .values(is_active=False)
        )
        changed += result.rowcount or 0

    if changed:
        await db.commit()
    return changed
