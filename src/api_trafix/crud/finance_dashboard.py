from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models import ParkingStatus, ParkTransaction

# ---------------------------------------------------------------------------
# Timezone helper (WIB = UTC+7)
# ---------------------------------------------------------------------------
WIB = timezone(timedelta(hours=7))


def get_today_range_wib_to_utc() -> tuple[datetime, datetime, str]:
    """
    Menentukan batas awal (00:00:00) dan akhir (23:59:59.999999) hari ini
    dalam zona waktu WIB, lalu mengonversikannya kembali ke UTC agar bisa
    dipakai untuk query ke database (yang menyimpan waktu dalam UTC).

    Returns:
        (start_utc, end_utc, date_label_wib)
    """
    now_wib = datetime.now(WIB)
    start_wib = now_wib.replace(hour=0, minute=0, second=0, microsecond=0)
    end_wib = now_wib.replace(hour=23, minute=59, second=59, microsecond=999999)

    start_utc = start_wib.astimezone(timezone.utc)
    end_utc = end_wib.astimezone(timezone.utc)
    date_label = now_wib.strftime("%Y-%m-%d")

    return start_utc, end_utc, date_label


# ---------------------------------------------------------------------------
# 1. Revenue Today
# ---------------------------------------------------------------------------
async def get_revenue_today(db: AsyncSession) -> dict:
    start_utc, end_utc, date_label = get_today_range_wib_to_utc()

    stmt = select(
        func.coalesce(func.sum(ParkTransaction.total_fee), 0).label("total_revenue"),
        func.count(ParkTransaction.id).label("total_transactions"),
    ).where(
        ParkTransaction.status_parking == ParkingStatus.COMPLETED,
        ParkTransaction.exit_time >= start_utc,
        ParkTransaction.exit_time <= end_utc,
    )

    result = await db.execute(stmt)
    row = result.one()

    return {
        "date": date_label,
        "total_revenue": row.total_revenue,
        "total_transactions": row.total_transactions,
    }


# ---------------------------------------------------------------------------
# 2. Revenue by Shift
# ---------------------------------------------------------------------------
async def get_revenue_by_shift(db: AsyncSession) -> dict:
    start_utc, end_utc, date_label = get_today_range_wib_to_utc()

    stmt = (
        select(
            ParkTransaction.exit_shift_id,
            func.coalesce(func.sum(ParkTransaction.total_fee), 0).label("total_revenue"),
            func.count(ParkTransaction.id).label("total_transactions"),
        )
        .where(
            ParkTransaction.status_parking == ParkingStatus.COMPLETED,
            ParkTransaction.exit_time >= start_utc,
            ParkTransaction.exit_time <= end_utc,
        )
        .group_by(ParkTransaction.exit_shift_id)
        .order_by(ParkTransaction.exit_shift_id)
    )

    result = await db.execute(stmt)
    rows = result.all()

    shifts = [
        {
            "exit_shift_id": row.exit_shift_id,
            "total_revenue": row.total_revenue,
            "total_transactions": row.total_transactions,
        }
        for row in rows
    ]

    return {"date": date_label, "shifts": shifts}


# ---------------------------------------------------------------------------
# 3. Vehicle Distribution
# ---------------------------------------------------------------------------
async def get_vehicle_distribution(db: AsyncSession) -> dict:
    start_utc, end_utc, date_label = get_today_range_wib_to_utc()

    stmt = (
        select(
            ParkTransaction.vehicle_type_id,
            func.count(ParkTransaction.id).label("total_vehicles"),
        )
        .where(
            ParkTransaction.entry_time >= start_utc,
            ParkTransaction.entry_time <= end_utc,
        )
        .group_by(ParkTransaction.vehicle_type_id)
        .order_by(ParkTransaction.vehicle_type_id)
    )

    result = await db.execute(stmt)
    rows = result.all()

    total_vehicles = sum(row.total_vehicles for row in rows)

    distribution = [
        {
            "vehicle_type_id": row.vehicle_type_id,
            "total_vehicles": row.total_vehicles,
            "percentage": round((row.total_vehicles / total_vehicles) * 100, 2)
            if total_vehicles > 0
            else 0.0,
        }
        for row in rows
    ]

    return {
        "date": date_label,
        "total_vehicles": total_vehicles,
        "distribution": distribution,
    }