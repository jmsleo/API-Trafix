import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models import ParkingStatus, ParkTransaction

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
        pattern = f"%{search}%"
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