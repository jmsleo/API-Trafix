import uuid
from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from api_trafix.models import MemberVehicle, ParkingStatus, ParkTransaction

_LOAD = (
    selectinload(ParkTransaction.vehicle_type),
    selectinload(ParkTransaction.member_vehicle).selectinload(MemberVehicle.member),
    selectinload(ParkTransaction.entry_gate),
    selectinload(ParkTransaction.exit_gate),
    selectinload(ParkTransaction.entry_shift),
    selectinload(ParkTransaction.exit_shift),
    selectinload(ParkTransaction.entry_operator),
    selectinload(ParkTransaction.exit_operator),
    selectinload(ParkTransaction.payments),
)


async def get_all(
    db: AsyncSession,
    search: str | None = None,
    status: ParkingStatus | None = None,
    vehicle_type_id: uuid.UUID | None = None,
    member_id: uuid.UUID | None = None,
    entry_from: datetime | None = None,
    entry_to: datetime | None = None,
    exit_from: datetime | None = None,
    exit_to: datetime | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[ParkTransaction], int]:
    stmt = select(ParkTransaction)
    count_stmt = select(func.count()).select_from(ParkTransaction)

    if search:
        like = f"%{search.strip()}%"
        condition = or_(
            ParkTransaction.police_number.ilike(like),
            ParkTransaction.ticket_number.ilike(like),
        )
        stmt = stmt.where(condition)
        count_stmt = count_stmt.where(condition)
    if status is not None:
        stmt = stmt.where(ParkTransaction.status_parking == status)
        count_stmt = count_stmt.where(ParkTransaction.status_parking == status)
    if vehicle_type_id is not None:
        stmt = stmt.where(ParkTransaction.vehicle_type_id == vehicle_type_id)
        count_stmt = count_stmt.where(ParkTransaction.vehicle_type_id == vehicle_type_id)
    if member_id is not None:
        stmt = stmt.join(
            MemberVehicle, ParkTransaction.member_vehicle_id == MemberVehicle.id
        ).where(MemberVehicle.member_id == member_id)
        count_stmt = count_stmt.join(
            MemberVehicle, ParkTransaction.member_vehicle_id == MemberVehicle.id
        ).where(MemberVehicle.member_id == member_id)
    if entry_from is not None:
        stmt = stmt.where(ParkTransaction.entry_time >= entry_from)
        count_stmt = count_stmt.where(ParkTransaction.entry_time >= entry_from)
    if entry_to is not None:
        stmt = stmt.where(ParkTransaction.entry_time <= entry_to)
        count_stmt = count_stmt.where(ParkTransaction.entry_time <= entry_to)
    if exit_from is not None:
        stmt = stmt.where(ParkTransaction.exit_time >= exit_from)
        count_stmt = count_stmt.where(ParkTransaction.exit_time >= exit_from)
    if exit_to is not None:
        stmt = stmt.where(ParkTransaction.exit_time <= exit_to)
        count_stmt = count_stmt.where(ParkTransaction.exit_time <= exit_to)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.options(*_LOAD)
        .order_by(ParkTransaction.entry_time.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(
    db: AsyncSession, transaction_id: uuid.UUID
) -> ParkTransaction | None:
    result = await db.execute(
        select(ParkTransaction)
        .where(ParkTransaction.id == transaction_id)
        .options(*_LOAD)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one_or_none()
