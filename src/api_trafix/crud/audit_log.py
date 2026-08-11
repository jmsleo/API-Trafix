import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.models.audit_logs import AuditLog

_USER_LOAD = selectinload(AuditLog.user)


def _coerce_utc(value: datetime | None) -> datetime | None:
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return value


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    module: str | None = None,
    action: str | None = None,
    role: str | None = None,
    user_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[AuditLog], int]:
    stmt = select(AuditLog)
    count_stmt = select(func.count()).select_from(AuditLog)

    if search:
        like = f"%{search.strip()}%"
        condition = AuditLog.description.ilike(like)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if module:
        condition = AuditLog.module == module.strip()
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if action:
        condition = AuditLog.action == action.strip()
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if role:
        condition = AuditLog.role == role.strip()
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if user_id is not None:
        condition = AuditLog.user_id == user_id
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if date_from is not None:
        condition = AuditLog.created_at >= _coerce_utc(date_from)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if date_to is not None:
        condition = AuditLog.created_at <= _coerce_utc(date_to)
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.options(_USER_LOAD)
        .order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(db: AsyncSession, audit_id: uuid.UUID) -> AuditLog | None:
    result = await db.execute(
        select(AuditLog).where(AuditLog.id == audit_id).options(_USER_LOAD)
    )
    return result.scalar_one_or_none()
