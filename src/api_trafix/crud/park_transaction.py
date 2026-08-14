import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models.park_transactions import ParkTransaction


async def get_by_code(db: AsyncSession, code: str) -> ParkTransaction | None:
    result = await db.execute(
        select(ParkTransaction)
        .where(ParkTransaction.ticket_number == code)
        .order_by(ParkTransaction.created_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def list_recent(db: AsyncSession, limit: int = 500) -> list[ParkTransaction]:
    result = await db.execute(
        select(ParkTransaction)
        .order_by(ParkTransaction.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def get_open_by_card(db: AsyncSession, card_number: str) -> ParkTransaction | None:
    result = await db.execute(
        select(ParkTransaction)
        .where(
            ParkTransaction.card_number == card_number,
            ParkTransaction.exit_time.is_(None),
        )
        .order_by(ParkTransaction.entry_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_open_by_plate(db: AsyncSession, plate: str) -> ParkTransaction | None:
    result = await db.execute(
        select(ParkTransaction)
        .where(
            ParkTransaction.police_number == plate,
            ParkTransaction.exit_time.is_(None),
        )
        .order_by(ParkTransaction.entry_time.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, transaction_id: uuid.UUID) -> ParkTransaction | None:
    result = await db.execute(
        select(ParkTransaction).where(ParkTransaction.id == transaction_id)
    )
    return result.scalar_one_or_none()
