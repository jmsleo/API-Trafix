import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models import Backup, BackupStatus


async def get_all(
    db: AsyncSession,
    status_filter: BackupStatus | None = None,
    search: str | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Backup], int]:
    stmt = select(Backup)
    count_stmt = select(func.count()).select_from(Backup)

    if status_filter is not None:
        stmt = stmt.where(Backup.status == status_filter)
        count_stmt = count_stmt.where(Backup.status == status_filter)
    if search:
        like = f"%{search.strip()}%"
        stmt = stmt.where(Backup.filename.ilike(like))
        count_stmt = count_stmt.where(Backup.filename.ilike(like))

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(Backup.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(db: AsyncSession, backup_id: uuid.UUID) -> Backup | None:
    result = await db.execute(select(Backup).where(Backup.id == backup_id))
    return result.scalar_one_or_none()
