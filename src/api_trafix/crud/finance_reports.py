import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models import ParkingStatus, ParkTransaction, Payment, PaymentStatus

WIB = timezone(timedelta(hours=7))


def _date_to_utc_range(d: date) -> tuple[datetime, datetime]:
    """Konversi satu tanggal (WIB) menjadi rentang awal-akhir hari dalam UTC."""
    start_wib = datetime.combine(d, time.min).replace(tzinfo=WIB)
    end_wib = datetime.combine(d, time.max).replace(tzinfo=WIB)
    return start_wib.astimezone(timezone.utc), end_wib.astimezone(timezone.utc)


async def get_transaction_report(
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    status: ParkingStatus | None = None,
    shift_id: uuid.UUID | None = None,
) -> dict:
    filters = []

    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                ParkTransaction.police_number.ilike(pattern),
                ParkTransaction.ticket_number.ilike(pattern),
            )
        )

    if start_date:
        start_utc, _ = _date_to_utc_range(start_date)
        filters.append(ParkTransaction.entry_time >= start_utc)

    if end_date:
        _, end_utc = _date_to_utc_range(end_date)
        filters.append(ParkTransaction.entry_time <= end_utc)

    if status:
        filters.append(ParkTransaction.status_parking == status)

    if shift_id:
        filters.append(
            or_(
                ParkTransaction.entry_shift_id == shift_id,
                ParkTransaction.exit_shift_id == shift_id,
            )
        )

    # --- Query 1: total baris (untuk metadata paginasi) ---
    count_stmt = select(func.count(ParkTransaction.id)).where(*filters)
    total_items = (await db.execute(count_stmt)).scalar_one()

    total_pages = (total_items + size - 1) // size if total_items > 0 else 0
    offset = (page - 1) * size

    # --- Query 2: data sebenarnya (offset + limit) ---
    data_stmt = (
        select(ParkTransaction)
        .where(*filters)
        .order_by(ParkTransaction.entry_time.desc())
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(data_stmt)
    items = result.scalars().all()

    return {
        "items": items,
        "pagination": {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": page,
            "size": size,
        },
    }

async def get_pending_ticket_report(
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
    entry_date: date | None = None,
    shift_id: uuid.UUID | None = None,
) -> dict:
    filters = [
        or_(
            ParkTransaction.status_parking == ParkingStatus.PARKED,
            Payment.status == PaymentStatus.PENDING,
        )
    ]
 
    if search:
        pattern = f"%{search.strip()}%"
        filters.append(
            or_(
                ParkTransaction.police_number.ilike(pattern),
                ParkTransaction.ticket_number.ilike(pattern),
            )
        )

    if entry_date:
        start_utc, end_utc = _date_to_utc_range(entry_date)
        filters.append(ParkTransaction.entry_time >= start_utc)
        filters.append(ParkTransaction.entry_time <= end_utc)
 
    if shift_id:
        filters.append(ParkTransaction.entry_shift_id == shift_id)
 
    # --- Query 1: total baris (untuk metadata paginasi) ---
    count_stmt = (
        select(func.count(func.distinct(ParkTransaction.id)))
        .select_from(ParkTransaction)
        .outerjoin(Payment, Payment.park_transaction_id == ParkTransaction.id)
        .where(*filters)
    )
    total_items = (await db.execute(count_stmt)).scalar_one()
 
    total_pages = (total_items + size - 1) // size if total_items > 0 else 0
    offset = (page - 1) * size
 
    # --- Query 2: data sebenarnya (offset + limit) ---
    data_stmt = (
        select(ParkTransaction, Payment.status.label("payment_status"))
        .select_from(ParkTransaction)
        .outerjoin(Payment, Payment.park_transaction_id == ParkTransaction.id)
        .where(*filters)
        .distinct()
        .order_by(ParkTransaction.entry_time.desc())
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(data_stmt)
    rows = result.all()
 
    items = []
    for row in rows:
        transaction = row.ParkTransaction
        payment_status = row.payment_status
        items.append(
            {
                "id": transaction.id,
                "ticket_number": transaction.ticket_number,
                "police_number": transaction.police_number,
                "vehicle_type_id": transaction.vehicle_type_id,
                "entry_time": transaction.entry_time,
                "entry_shift_id": transaction.entry_shift_id,
                "status_parking": transaction.status_parking,
                "payment_status": payment_status.value if payment_status else None,
            }
        )
 
    return {
        "items": items,
        "pagination": {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": page,
            "size": size,
        },
    }