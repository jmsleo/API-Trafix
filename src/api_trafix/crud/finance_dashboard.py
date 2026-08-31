import uuid as uuid_mod
from datetime import date as date_type
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models import (
    ParkingStatus,
    ParkTransaction,
    Payment,
    PaymentStatus,
    VehicleType,
)
from api_trafix.models.shifts import Shift, ShiftStatus as ShiftStatusModel

# ---------------------------------------------------------------------------
# Timezone helper (WIB = UTC+7)
# ---------------------------------------------------------------------------
WIB = timezone(timedelta(hours=7))


def get_date_range_wib_to_utc(
    target_date: date_type | None = None,
) -> tuple[datetime, datetime, str]:
    """
    Menentukan batas awal (00:00:00) dan akhir (23:59:59.999999) untuk
    tanggal tertentu dalam zona waktu WIB, lalu mengonversikannya ke UTC.

    Jika target_date is None, pakai hari ini (WIB).

    Returns:
        (start_utc, end_utc, date_label_wib)
    """
    if target_date is None:
        target = datetime.now(WIB).date()
    else:
        target = target_date

    start_wib = datetime(target.year, target.month, target.day, 0, 0, 0, 0, tzinfo=WIB)
    end_wib = datetime(target.year, target.month, target.day, 23, 59, 59, 999999, tzinfo=WIB)

    return start_wib.astimezone(timezone.utc), end_wib.astimezone(timezone.utc), str(target)


# Keep the old name as an alias so existing callers (e.g. route _cache_key) still work.
def get_today_range_wib_to_utc() -> tuple[datetime, datetime, str]:
    return get_date_range_wib_to_utc(None)


def _get_yesterday_date(target_date: date_type | None = None) -> date_type:
    """Return the day before *target_date* (defaults to today WIB)."""
    if target_date is None:
        return datetime.now(WIB).date() - timedelta(days=1)
    return target_date - timedelta(days=1)


# ---------------------------------------------------------------------------
# Helper: persentase pertumbuhan yang aman terhadap division by zero
# ---------------------------------------------------------------------------
def safe_growth_percentage(current: int, previous: int) -> float:
    if previous == 0:
        # Jika kemarin 0 dan hari ini juga 0 -> tidak ada pertumbuhan.
        # Jika kemarin 0 dan hari ini > 0 -> anggap kenaikan 100%.
        return 0.0 if current == 0 else 100.0
    return round(((current - previous) / previous) * 100, 2)


# ---------------------------------------------------------------------------
# 0. Active Shifts (for dropdown filter)
# ---------------------------------------------------------------------------
async def get_active_shifts(db: AsyncSession) -> list[dict]:
    """Daftar shift aktif untuk dropdown filter dashboard."""
    stmt = (
        select(Shift.id, Shift.name)
        .where(Shift.status == ShiftStatusModel.ACTIVE)
        .order_by(Shift.name)
    )
    result = await db.execute(stmt)
    return [{"id": str(row.id), "name": row.name} for row in result.all()]


# ---------------------------------------------------------------------------
# 1. Revenue Today
# ---------------------------------------------------------------------------
async def get_revenue_today(
    db: AsyncSession,
    *,
    target_date: date_type | None = None,
    shift_id: uuid_mod.UUID | None = None,
) -> dict:
    start_utc, end_utc, date_label = get_date_range_wib_to_utc(target_date)

    stmt = select(
        func.coalesce(func.sum(ParkTransaction.total_fee), 0).label("total_revenue"),
        func.count(ParkTransaction.id).label("total_transactions"),
    ).where(
        ParkTransaction.status_parking == ParkingStatus.COMPLETED,
        ParkTransaction.exit_time >= start_utc,
        ParkTransaction.exit_time <= end_utc,
    )

    if shift_id is not None:
        stmt = stmt.where(ParkTransaction.exit_shift_id == shift_id)

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
async def get_revenue_by_shift(
    db: AsyncSession,
    *,
    target_date: date_type | None = None,
    shift_id: uuid_mod.UUID | None = None,
) -> dict:
    start_utc, end_utc, date_label = get_date_range_wib_to_utc(target_date)

    stmt = (
        select(
            ParkTransaction.exit_shift_id,
            Shift.name.label("shift_name"),
            func.coalesce(func.sum(ParkTransaction.total_fee), 0).label("total_revenue"),
            func.count(ParkTransaction.id).label("total_transactions"),
        )
        .outerjoin(Shift, ParkTransaction.exit_shift_id == Shift.id)
        .where(
            ParkTransaction.status_parking == ParkingStatus.COMPLETED,
            ParkTransaction.exit_time >= start_utc,
            ParkTransaction.exit_time <= end_utc,
        )
        .group_by(ParkTransaction.exit_shift_id, Shift.name)
        .order_by(ParkTransaction.exit_shift_id)
    )

    if shift_id is not None:
        stmt = stmt.where(ParkTransaction.exit_shift_id == shift_id)

    result = await db.execute(stmt)
    rows = result.all()

    shifts = [
        {
            "exit_shift_id": row.exit_shift_id,
            "shift_name": row.shift_name,
            "total_revenue": row.total_revenue,
            "total_transactions": row.total_transactions,
        }
        for row in rows
    ]

    return {"date": date_label, "shifts": shifts}


# ---------------------------------------------------------------------------
# 3. Vehicle Distribution
# ---------------------------------------------------------------------------
async def get_vehicle_distribution(
    db: AsyncSession,
    *,
    target_date: date_type | None = None,
    shift_id: uuid_mod.UUID | None = None,
) -> dict:
    start_utc, end_utc, date_label = get_date_range_wib_to_utc(target_date)

    stmt = (
        select(
            ParkTransaction.vehicle_type_id,
            VehicleType.name.label("vehicle_type_name"),
            func.count(ParkTransaction.id).label("total_vehicles"),
        )
        .outerjoin(VehicleType, ParkTransaction.vehicle_type_id == VehicleType.id)
        .where(
            ParkTransaction.entry_time >= start_utc,
            ParkTransaction.entry_time <= end_utc,
        )
        .group_by(ParkTransaction.vehicle_type_id, VehicleType.name)
        .order_by(ParkTransaction.vehicle_type_id)
    )

    if shift_id is not None:
        stmt = stmt.where(ParkTransaction.entry_shift_id == shift_id)

    result = await db.execute(stmt)
    rows = result.all()

    total_vehicles = sum(row.total_vehicles for row in rows)

    distribution = [
        {
            "vehicle_type_id": row.vehicle_type_id,
            "vehicle_type_name": row.vehicle_type_name or "Unknown",
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


# ---------------------------------------------------------------------------
# 4. Payment Distribution
# ---------------------------------------------------------------------------
async def get_payment_distribution(
    db: AsyncSession,
    *,
    target_date: date_type | None = None,
    shift_id: uuid_mod.UUID | None = None,
) -> dict:
    start_utc, end_utc, date_label = get_date_range_wib_to_utc(target_date)

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

    if shift_id is not None:
        stmt = stmt.where(ParkTransaction.exit_shift_id == shift_id)

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


# ---------------------------------------------------------------------------
# 5. Executive Insight
# ---------------------------------------------------------------------------
async def get_executive_insight(
    db: AsyncSession,
    *,
    target_date: date_type | None = None,
    shift_id: uuid_mod.UUID | None = None,
) -> dict:
    start_today_utc, end_today_utc, date_label = get_date_range_wib_to_utc(target_date)
    yesterday = _get_yesterday_date(target_date)
    start_yesterday_utc, end_yesterday_utc, _ = get_date_range_wib_to_utc(yesterday)

    # --- Revenue hari ini ---
    stmt_revenue_today = select(
        func.coalesce(func.sum(ParkTransaction.total_fee), 0)
    ).where(
        ParkTransaction.status_parking == ParkingStatus.COMPLETED,
        ParkTransaction.exit_time >= start_today_utc,
        ParkTransaction.exit_time <= end_today_utc,
    )
    if shift_id is not None:
        stmt_revenue_today = stmt_revenue_today.where(
            ParkTransaction.exit_shift_id == shift_id
        )
    revenue_today = (await db.execute(stmt_revenue_today)).scalar_one()

    # --- Revenue kemarin ---
    stmt_revenue_yesterday = select(
        func.coalesce(func.sum(ParkTransaction.total_fee), 0)
    ).where(
        ParkTransaction.status_parking == ParkingStatus.COMPLETED,
        ParkTransaction.exit_time >= start_yesterday_utc,
        ParkTransaction.exit_time <= end_yesterday_utc,
    )
    if shift_id is not None:
        stmt_revenue_yesterday = stmt_revenue_yesterday.where(
            ParkTransaction.exit_shift_id == shift_id
        )
    revenue_yesterday = (await db.execute(stmt_revenue_yesterday)).scalar_one()

    revenue_growth_percentage = safe_growth_percentage(revenue_today, revenue_yesterday)

    # --- Shift dengan pendapatan tertinggi hari ini ---
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
    if shift_id is not None:
        stmt_highest_shift = stmt_highest_shift.where(
            ParkTransaction.exit_shift_id == shift_id
        )
    highest_shift_row = (await db.execute(stmt_highest_shift)).first()
    highest_revenue_shift_id = highest_shift_row.exit_shift_id if highest_shift_row else None

    # --- Total tiket pending hari ini ---
    # PARKED (belum keluar) ATAU pembayarannya masih PENDING, berdasarkan entry_time hari ini
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
    if shift_id is not None:
        stmt_pending = stmt_pending.where(
            ParkTransaction.entry_shift_id == shift_id
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