import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.models import (
    Gate,
    GateEvent,
    MemberStatus,
    OperatorSession,
    ParkingStatus,
    ParkTransaction,
    Payment,
    PaymentMethod,
    PaymentStatus,
    User,
    UserRole,
    VehicleType,
)

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
        select(ParkTransaction, VehicleType.name.label("vehicle_type_name"), User.name.label("exit_operator_name"))
        .outerjoin(VehicleType, ParkTransaction.vehicle_type_id == VehicleType.id)
        .outerjoin(User, ParkTransaction.exit_operator_id == User.id)
        .where(*filters)
        .order_by(ParkTransaction.entry_time.desc())
        .offset(offset)
        .limit(size)
    )
    result = await db.execute(data_stmt)
    rows = result.all()

    # Satu query tambahan untuk metode pembayaran (hindari N+1): ambil metode
    # pembayaran SUCCESS pertama untuk setiap transaksi pada halaman ini.
    tx_ids = [row.ParkTransaction.id for row in rows]
    method_by_tx: dict[uuid.UUID, str] = {}
    if tx_ids:
        pay_stmt = (
            select(Payment.park_transaction_id, Payment.method)
            .where(
                Payment.park_transaction_id.in_(tx_ids),
                Payment.status == PaymentStatus.SUCCESS,
            )
            .order_by(Payment.paid_at.asc())
        )
        for tx_id, method in (await db.execute(pay_stmt)).all():
            method_by_tx.setdefault(tx_id, method.value if isinstance(method, PaymentMethod) else str(method))

    items = [
        {
            "id": row.ParkTransaction.id,
            "ticket_number": row.ParkTransaction.ticket_number,
            "police_number": row.ParkTransaction.police_number,
            "vehicle_type_id": row.ParkTransaction.vehicle_type_id,
            "vehicle_type_name": row.vehicle_type_name,
            "entry_time": row.ParkTransaction.entry_time,
            "exit_time": row.ParkTransaction.exit_time,
            "entry_shift_id": row.ParkTransaction.entry_shift_id,
            "exit_shift_id": row.ParkTransaction.exit_shift_id,
            "status_parking": row.ParkTransaction.status_parking,
            "total_fee": row.ParkTransaction.total_fee,
            "exit_operator_name": row.exit_operator_name,
            "payment_method": method_by_tx.get(row.ParkTransaction.id),
        }
        for row in rows
    ]

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
        select(
            ParkTransaction,
            Payment.status.label("payment_status"),
            Gate.name.label("entry_gate_name"),
            VehicleType.name.label("vehicle_type_name"),
        )
        .select_from(ParkTransaction)
        .outerjoin(Payment, Payment.park_transaction_id == ParkTransaction.id)
        .outerjoin(Gate, ParkTransaction.entry_gate_id == Gate.id)
        .outerjoin(VehicleType, ParkTransaction.vehicle_type_id == VehicleType.id)
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
                "vehicle_type_name": row.vehicle_type_name,
                "entry_time": transaction.entry_time,
                "entry_shift_id": transaction.entry_shift_id,
                "status_parking": transaction.status_parking,
                "payment_status": payment_status.value if payment_status else None,
                "entry_gate_name": row.entry_gate_name,
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


# ---------------------------------------------------------------------------
# Helpers untuk laporan rentang tanggal (WIB)
# ---------------------------------------------------------------------------


def _range_to_utc(
    start_date: date | None, end_date: date | None
) -> tuple[datetime | None, datetime | None]:
    """Konversi rentang tanggal (WIB) menjadi batas bawah-atas UTC.

    Tanpa argumen mengembalikan (None, None) sehingga laporan mencakup
    seluruh riwayat.
    """
    start_utc = _date_to_utc_range(start_date)[0] if start_date else None
    end_utc = _date_to_utc_range(end_date)[1] if end_date else None
    return start_utc, end_utc


def _wib_day_bucket(column):
    """Ekspresi SQL: kalender hari (WIB) dari kolom timestamptz."""
    return func.date(func.timezone("Asia/Jakarta", column))


async def get_revenue_report(
    db: AsyncSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Laporan pendapatan harian + rincian metode pembayaran.

    Semantik sama dengan dashboard: transaksi COMPLETED, pendapatan dihitung
    dari total_fee berdasarkan exit_time (WIB). Breakdown metode pembayaran
    dihitung dari record Payment berstatus SUCCESS.
    """
    start_utc, end_utc = _range_to_utc(start_date, end_date)

    filters = [ParkTransaction.status_parking == ParkingStatus.COMPLETED]
    if start_utc:
        filters.append(ParkTransaction.exit_time >= start_utc)
    if end_utc:
        filters.append(ParkTransaction.exit_time <= end_utc)

    # --- Rincian harian ---
    daily_stmt = (
        select(
            _wib_day_bucket(ParkTransaction.exit_time).label("day"),
            func.coalesce(func.sum(ParkTransaction.total_fee), 0).label("total_revenue"),
            func.count(ParkTransaction.id).label("total_transactions"),
        )
        .where(*filters)
        .group_by("day")
        .order_by("day")
    )
    daily_rows = (await db.execute(daily_stmt)).all()

    items = [
        {
            "date": row.day,
            "total_revenue": row.total_revenue,
            "total_transactions": row.total_transactions,
        }
        for row in daily_rows
    ]
    summary = {
        "total_revenue": sum(i["total_revenue"] for i in items),
        "total_transactions": sum(i["total_transactions"] for i in items),
    }

    # --- Rincian metode pembayaran ---
    method_filters = [
        Payment.status == PaymentStatus.SUCCESS,
        ParkTransaction.status_parking == ParkingStatus.COMPLETED,
    ]
    if start_utc:
        method_filters.append(Payment.paid_at >= start_utc)
    if end_utc:
        method_filters.append(Payment.paid_at <= end_utc)

    method_stmt = (
        select(
            Payment.method,
            func.count(func.distinct(Payment.id)).label("total_transactions"),
            func.coalesce(func.sum(Payment.amount), 0).label("total_amount"),
        )
        .select_from(Payment)
        .join(ParkTransaction, Payment.park_transaction_id == ParkTransaction.id)
        .where(*method_filters)
        .group_by(Payment.method)
        .order_by(func.sum(Payment.amount).desc())
    )
    method_rows = (await db.execute(method_stmt)).all()

    grand_total = sum(row.total_amount for row in method_rows)
    payment_methods = [
        {
            "method": row.method.value if isinstance(row.method, PaymentMethod) else str(row.method),
            "total_transactions": row.total_transactions,
            "total_amount": row.total_amount,
            "percentage": round((row.total_amount / grand_total * 100), 2) if grand_total else 0.0,
        }
        for row in method_rows
    ]

    return {"summary": summary, "items": items, "payment_methods": payment_methods}


async def get_vehicle_summary_report(
    db: AsyncSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Ringkasan kendaraan per jenis: jumlah transaksi dan pendapatan."""
    start_utc, end_utc = _range_to_utc(start_date, end_date)

    filters = [ParkTransaction.status_parking == ParkingStatus.COMPLETED]
    if start_utc:
        filters.append(ParkTransaction.exit_time >= start_utc)
    if end_utc:
        filters.append(ParkTransaction.exit_time <= end_utc)

    stmt = (
        select(
            ParkTransaction.vehicle_type_id,
            VehicleType.name.label("vehicle_type_name"),
            func.count(ParkTransaction.id).label("total_vehicles"),
            func.coalesce(func.sum(ParkTransaction.total_fee), 0).label("total_revenue"),
        )
        .outerjoin(VehicleType, ParkTransaction.vehicle_type_id == VehicleType.id)
        .where(*filters)
        .group_by(ParkTransaction.vehicle_type_id, VehicleType.name)
        .order_by(func.sum(ParkTransaction.total_fee).desc())
    )
    rows = (await db.execute(stmt)).all()

    items = [
        {
            "vehicle_type_id": row.vehicle_type_id,
            "vehicle_type_name": row.vehicle_type_name or "Unknown",
            "total_vehicles": row.total_vehicles,
            "total_revenue": row.total_revenue,
        }
        for row in rows
    ]
    summary = {
        "total_revenue": sum(i["total_revenue"] for i in items),
        "total_transactions": sum(i["total_vehicles"] for i in items),
    }
    return {"summary": summary, "items": items}


async def get_operator_performance_report(
    db: AsyncSession,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Kinerja operator: jumlah sesi, transaksi yang ditangani, dan pendapatan.

    Transaksi diatribusikan ke operator exit (exit_operator_id); sesi dihitung
    dari OperatorSession yang beririsan dengan rentang tanggal.
    """
    start_utc, end_utc = _range_to_utc(start_date, end_date)

    tx_filters = [
        ParkTransaction.status_parking == ParkingStatus.COMPLETED,
        ParkTransaction.exit_operator_id.isnot(None),
    ]
    if start_utc:
        tx_filters.append(ParkTransaction.exit_time >= start_utc)
    if end_utc:
        tx_filters.append(ParkTransaction.exit_time <= end_utc)

    tx_stmt = (
        select(
            ParkTransaction.exit_operator_id.label("operator_id"),
            func.count(ParkTransaction.id).label("total_transactions"),
            func.coalesce(func.sum(ParkTransaction.total_fee), 0).label("total_revenue"),
        )
        .where(*tx_filters)
        .group_by(ParkTransaction.exit_operator_id)
    )
    tx_rows = (await db.execute(tx_stmt)).all()
    tx_by_operator = {row.operator_id: row for row in tx_rows}

    session_filters = []
    if start_utc and end_utc:
        session_filters.append(OperatorSession.login_time <= end_utc)
        session_filters.append(
            or_(OperatorSession.logout_time.is_(None), OperatorSession.logout_time >= start_utc)
        )

    session_stmt = (
        select(
            OperatorSession.user_id.label("operator_id"),
            func.count(OperatorSession.id).label("total_sessions"),
        )
        .where(*session_filters)
        .group_by(OperatorSession.user_id)
    )
    session_rows = (await db.execute(session_stmt)).all()
    sessions_by_operator = {row.operator_id: row.total_sessions for row in session_rows}

    operator_stmt = select(User).where(User.role == UserRole.OPERATOR).order_by(User.name)
    operators = (await db.execute(operator_stmt)).scalars().all()

    items = []
    for op in operators:
        stats = tx_by_operator.get(op.id)
        total_transactions = stats.total_transactions if stats else 0
        total_revenue = stats.total_revenue if stats else 0
        items.append(
            {
                "operator_id": op.id,
                "operator_name": op.name,
                "total_sessions": sessions_by_operator.get(op.id, 0),
                "total_transactions": total_transactions,
                "total_revenue": total_revenue,
                "avg_transaction_value": (
                    round(total_revenue / total_transactions, 2) if total_transactions else 0.0
                ),
            }
        )

    items.sort(key=lambda i: i["total_revenue"], reverse=True)
    return {"items": items}


async def get_member_report(
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
    search: str | None = None,
    status: MemberStatus | None = None,
) -> dict:
    """Laporan member (read-only) untuk role finance.

    Memanfaatkan crud.member.get_all agar logika pencarian (termasuk nomor
    polisi kendaraan) konsisten dengan endpoint admin /members.
    """
    from api_trafix.crud import member as member_crud

    members, total_items = await member_crud.get_all(
        db, search=search, status=status, page=page, page_size=size
    )

    items = []
    for m in members:
        latest_sub = max(m.subscriptions, key=lambda s: s.start_date, default=None)
        plan = None
        if latest_sub is not None and latest_sub.plan is not None:
            plan = {
                "name": latest_sub.plan.name,
                "price": latest_sub.plan.price,
                "status": latest_sub.status,
            }
        items.append(
            {
                "id": m.id,
                "member_code": m.member_code,
                "name": m.name,
                "status": m.status,
                "created_at": m.created_at,
                "vehicles": [
                    {
                        "police_number": v.police_number,
                        "vehicle_type_name": (
                            v.vehicle_type.name if v.vehicle_type is not None else None
                        ),
                    }
                    for v in m.vehicles
                ],
                "plan": plan,
            }
        )

    total_pages = (total_items + size - 1) // size if total_items > 0 else 0
    return {
        "items": items,
        "pagination": {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": page,
            "size": size,
        },
    }


async def get_gate_events_report(
    db: AsyncSession,
    page: int = 1,
    size: int = 20,
    gate_code: str | None = None,
    source: str | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """Log akses gate (audit trail keputusan hardware) dengan pagination."""
    filters = []

    if gate_code:
        filters.append(GateEvent.gate_code == gate_code.strip())
    if source:
        filters.append(GateEvent.source.ilike(f"%{source.strip()}%"))
    if start_date:
        start_utc, _ = _date_to_utc_range(start_date)
        filters.append(GateEvent.ts >= start_utc)
    if end_date:
        _, end_utc = _date_to_utc_range(end_date)
        filters.append(GateEvent.ts <= end_utc)

    count_stmt = select(func.count(GateEvent.id)).where(*filters)
    total_items = (await db.execute(count_stmt)).scalar_one()

    total_pages = (total_items + size - 1) // size if total_items > 0 else 0
    offset = (page - 1) * size

    data_stmt = (
        select(GateEvent)
        .where(*filters)
        .order_by(GateEvent.ts.desc())
        .offset(offset)
        .limit(size)
    )
    rows = (await db.execute(data_stmt)).scalars().all()

    items = [
        {
            "id": ev.id,
            "ts": ev.ts,
            "gate_code": ev.gate_code,
            "source": ev.source,
            "method": ev.method,
            "ticket_number": ev.ticket_number,
            "detail": ev.detail,
        }
        for ev in rows
    ]

    return {
        "items": items,
        "pagination": {
            "total_items": total_items,
            "total_pages": total_pages,
            "current_page": page,
            "size": size,
        },
    }