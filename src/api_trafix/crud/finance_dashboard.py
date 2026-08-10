from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models import ParkingStatus, ParkTransaction, Payment, PaymentStatus

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


def get_yesterday_range_wib_to_utc() -> tuple[datetime, datetime, str]:
    """
    Sama seperti get_today_range_wib_to_utc(), tapi untuk tanggal kemarin
    (WIB), lalu dikonversikan ke UTC.
    """
    now_wib = datetime.now(WIB)
    yesterday_wib = now_wib - timedelta(days=1)
 
    start_wib = yesterday_wib.replace(hour=0, minute=0, second=0, microsecond=0)
    end_wib = yesterday_wib.replace(hour=23, minute=59, second=59, microsecond=999999)
 
    start_utc = start_wib.astimezone(timezone.utc)
    end_utc = end_wib.astimezone(timezone.utc)
    date_label = yesterday_wib.strftime("%Y-%m-%d")
 
    return start_utc, end_utc, date_label
 
 
def safe_growth_percentage(current: int, previous: int) -> float:
    if previous == 0:
        # Jika kemarin 0 dan hari ini juga 0 -> tidak ada pertumbuhan.
        # Jika kemarin 0 dan hari ini > 0 -> anggap kenaikan 100%.
        return 0.0 if current == 0 else 100.0
    return round(((current - previous) / previous) * 100, 2)
 
 
async def get_payment_distribution(db: AsyncSession) -> dict:
    start_utc, end_utc, date_label = get_today_range_wib_to_utc()
 
    stmt = (
        select(
            Payment.method,
            func.count(Payment.id).label("total_transactions"),
            func.coalesce(func.sum(Payment.amount), 0).label("total_amount"),
        )
        .join(ParkTransaction, ParkTransaction.id == Payment.park_transaction_id)
        .where(
            ParkTransaction.status_parking == ParkingStatus.COMPLETED,
            Payment.status == PaymentStatus.SUCCESS,
            ParkTransaction.exit_time >= start_utc,
            ParkTransaction.exit_time <= end_utc,
        )
        .group_by(Payment.method)
        .order_by(Payment.method)
    )
 
    result = await db.execute(stmt)
    rows = result.all()
 
    total_amount = sum(row.total_amount for row in rows)
    total_transactions = sum(row.total_transactions for row in rows)
 
    distribution = [
        {
            "payment_method": row.method.value
            if hasattr(row.method, "value")
            else row.method,
            "total_transactions": row.total_transactions,
            "total_amount": row.total_amount,
            "percentage": round((row.total_amount / total_amount) * 100, 2)
            if total_amount > 0
            else 0.0,
        }
        for row in rows
    ]
 
    return {
        "date": date_label,
        "total_transactions": total_transactions,
        "total_amount": total_amount,
        "distribution": distribution,
    }
 
 
async def get_executive_insight(db: AsyncSession) -> dict:
    start_today_utc, end_today_utc, date_label = get_today_range_wib_to_utc()
    start_yesterday_utc, end_yesterday_utc, _ = get_yesterday_range_wib_to_utc()
 
    # --- Revenue hari ini ---
    stmt_revenue_today = select(
        func.coalesce(func.sum(ParkTransaction.total_fee), 0)
    ).where(
        ParkTransaction.status_parking == ParkingStatus.COMPLETED,
        ParkTransaction.exit_time >= start_today_utc,
        ParkTransaction.exit_time <= end_today_utc,
    )
    revenue_today = (await db.execute(stmt_revenue_today)).scalar_one()

    stmt_revenue_yesterday = select(
        func.coalesce(func.sum(ParkTransaction.total_fee), 0)
    ).where(
        ParkTransaction.status_parking == ParkingStatus.COMPLETED,
        ParkTransaction.exit_time >= start_yesterday_utc,
        ParkTransaction.exit_time <= end_yesterday_utc,
    )
    revenue_yesterday = (await db.execute(stmt_revenue_yesterday)).scalar_one()
 
    revenue_growth_percentage = safe_growth_percentage(revenue_today, revenue_yesterday)
 
    stmt_highest_shift = (
        select(
            ParkTransaction.exit_shift_id,
            func.coalesce(func.sum(ParkTransaction.total_fee), 0).label("shift_revenue"),
        )
        .where(
            ParkTransaction.status_parking == ParkingStatus.COMPLETED,
            ParkTransaction.exit_time >= start_today_utc,
            ParkTransaction.exit_time <= end_today_utc,
        )
        .group_by(ParkTransaction.exit_shift_id)
        .order_by(func.sum(ParkTransaction.total_fee).desc())
        .limit(1)
    )
    highest_shift_row = (await db.execute(stmt_highest_shift)).first()
    highest_revenue_shift_id = highest_shift_row.exit_shift_id if highest_shift_row else None

    stmt_pending = (
        select(func.count(func.distinct(ParkTransaction.id)))
        .outerjoin(Payment, Payment.park_transaction_id == ParkTransaction.id)
        .where(
            ParkTransaction.entry_time >= start_today_utc,
            ParkTransaction.entry_time <= end_today_utc,
            or_(
                ParkTransaction.status_parking == ParkingStatus.PARKED,
                Payment.status == PaymentStatus.PENDING,
            ),
        )
    )
    total_pending_tickets = (await db.execute(stmt_pending)).scalar_one()
 
    return {
        "date": date_label,
        "revenue_today": revenue_today,
        "revenue_yesterday": revenue_yesterday,
        "revenue_growth_percentage": revenue_growth_percentage,
        "highest_revenue_shift_id": highest_revenue_shift_id,
        "total_pending_tickets": total_pending_tickets,
    }
