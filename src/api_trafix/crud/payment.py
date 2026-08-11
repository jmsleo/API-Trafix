import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models import Payment, PaymentMethod, PaymentStatus


async def get_all(
    db: AsyncSession,
    park_transaction_id: uuid.UUID | None = None,
    method: PaymentMethod | None = None,
    status: PaymentStatus | None = None,
    paid_from: datetime | None = None,
    paid_to: datetime | None = None,
    page: int = 1,
    page_size: int = 10,
) -> tuple[list[Payment], int]:
    stmt = select(Payment)
    count_stmt = select(func.count()).select_from(Payment)

    if park_transaction_id is not None:
        stmt = stmt.where(Payment.park_transaction_id == park_transaction_id)
        count_stmt = count_stmt.where(Payment.park_transaction_id == park_transaction_id)
    if method is not None:
        stmt = stmt.where(Payment.method == method)
        count_stmt = count_stmt.where(Payment.method == method)
    if status is not None:
        stmt = stmt.where(Payment.status == status)
        count_stmt = count_stmt.where(Payment.status == status)
    if paid_from is not None:
        stmt = stmt.where(Payment.paid_at >= paid_from)
        count_stmt = count_stmt.where(Payment.paid_at >= paid_from)
    if paid_to is not None:
        stmt = stmt.where(Payment.paid_at <= paid_to)
        count_stmt = count_stmt.where(Payment.paid_at <= paid_to)

    total = (await db.execute(count_stmt)).scalar_one()
    stmt = (
        stmt.order_by(Payment.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all()), total


async def get_by_id(db: AsyncSession, payment_id: uuid.UUID) -> Payment | None:
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    return result.scalar_one_or_none()


async def refund(db: AsyncSession, db_obj: Payment) -> Payment:
    db_obj.status = PaymentStatus.REFUNDED
    await db.commit()
    return db_obj
