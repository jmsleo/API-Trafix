import uuid
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.models.operator_sessions import OperatorSession, OperatorSessionStatus
from api_trafix.models.users import User
from api_trafix.schemas.operator_session import OperatorSessionStart


async def get_all(
    db: AsyncSession,
    operator_id: uuid.UUID | None = None,
    status: OperatorSessionStatus | None = None,
    login_from: datetime | None = None,
    login_to: datetime | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[OperatorSession], int]:
    stmt = select(OperatorSession).options(
        selectinload(OperatorSession.user),
        selectinload(OperatorSession.shift),
        selectinload(OperatorSession.gate),
    )
    count_stmt = select(func.count()).select_from(OperatorSession)

    if operator_id is not None:
        stmt = stmt.where(OperatorSession.user_id == operator_id)
        count_stmt = count_stmt.where(OperatorSession.user_id == operator_id)
    if status is not None:
        stmt = stmt.where(OperatorSession.status == status)
        count_stmt = count_stmt.where(OperatorSession.status == status)
    if login_from is not None:
        stmt = stmt.where(OperatorSession.login_time >= login_from)
        count_stmt = count_stmt.where(OperatorSession.login_time >= login_from)
    if login_to is not None:
        stmt = stmt.where(OperatorSession.login_time <= login_to)
        count_stmt = count_stmt.where(OperatorSession.login_time <= login_to)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(OperatorSession.login_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(
    db: AsyncSession, session_id: uuid.UUID
) -> OperatorSession | None:
    result = await db.execute(
        select(OperatorSession)
        .where(OperatorSession.id == session_id)
        .options(
            selectinload(OperatorSession.user),
            selectinload(OperatorSession.shift),
            selectinload(OperatorSession.gate),
        )
    )
    return result.scalar_one_or_none()


async def get_active_for_operator(
    db: AsyncSession, operator_id: uuid.UUID
) -> OperatorSession | None:
    result = await db.execute(
        select(OperatorSession).where(
            OperatorSession.user_id == operator_id,
            OperatorSession.status == OperatorSessionStatus.ACTIVE,
        )
    )
    return result.scalar_one_or_none()


async def start(
    db: AsyncSession, payload: OperatorSessionStart, operator: User
) -> OperatorSession:
    db_obj = OperatorSession(
        user_id=operator.id,
        shift_id=payload.shift_id,
        gate_id=payload.gate_id,
        login_time=datetime.now(timezone.utc),
        status=OperatorSessionStatus.ACTIVE,
    )
    db.add(db_obj)
    await db.commit()
    return await get_by_id(db, db_obj.id)


async def end(db: AsyncSession, db_obj: OperatorSession) -> OperatorSession:
    db_obj.logout_time = datetime.now(timezone.utc)
    db_obj.status = OperatorSessionStatus.CLOSED
    await db.commit()
    return await get_by_id(db, db_obj.id)
