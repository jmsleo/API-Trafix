import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.core.dependencies import get_current_finance
from api_trafix.crud import finance_reports as crud_reports
from api_trafix.config.database import get_db
from api_trafix.models import MemberStatus, ParkingStatus, User
from api_trafix.schemas.finance_reports import (
    GateEventReportResponse,
    MemberReportResponse,
    OperatorPerformanceResponse,
    PendingTicketResponse,
    RevenueReportResponse,
    TransactionReportResponse,
    VehicleReportResponse,
)
from api_trafix.services.report_export import (
    EXPORT_MAX_ROWS,
    ExportDocument,
    ExportFormat,
    ExportTable,
    build_export_response,
    duration_minutes,
    enum_value,
    fmt_date,
    fmt_dt,
    period_label,
    rp,
)

router = APIRouter(prefix="/finance/reports", tags=["Finance Reports"])


def _guard_export_size(total_items: int) -> None:
    if total_items > EXPORT_MAX_ROWS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Data terlalu besar untuk diekspor ({total_items} baris, "
                f"maksimal {EXPORT_MAX_ROWS}). Persempit rentang tanggal."
            ),
        )


def _summary_lines(total_items: int | None = None) -> list[str]:
    if total_items is None:
        return []
    return [f"Jumlah data: {total_items}"]


@router.get("/transactions", response_model=TransactionReportResponse)
async def transaction_report(
    page: int = Query(1, ge=1, description="Nomor halaman"),
    size: int = Query(20, ge=1, le=100, description="Jumlah data per halaman (max 100)"),
    search: str | None = Query(
        None, description="Cari berdasarkan police_number atau ticket_number"
    ),
    start_date: date | None = Query(None, description="Format YYYY-MM-DD"),
    end_date: date | None = Query(None, description="Format YYYY-MM-DD"),
    status: ParkingStatus | None = Query(None, description="Filter status parkir"),
    shift_id: uuid.UUID | None = Query(
        None, description="Filter berdasarkan entry_shift_id atau exit_shift_id"
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Laporan transaksi dengan pagination, search, dan filter."""
    data = await crud_reports.get_transaction_report(
        db=db,
        page=page,
        size=size,
        search=search,
        start_date=start_date,
        end_date=end_date,
        status=status,
        shift_id=shift_id,
    )
    return data

@router.get("/pending-tickets", response_model=PendingTicketResponse)
async def pending_ticket_report(
    page: int = Query(1, ge=1, description="Nomor halaman"),
    size: int = Query(20, ge=1, le=100, description="Jumlah data per halaman (max 100)"),
    search: str | None = Query(
        None, description="Cari berdasarkan police_number atau ticket_number"
    ),
    entry_date: date | None = Query(None, description="Filter hari masuk, format YYYY-MM-DD"),
    shift_id: uuid.UUID | None = Query(None, description="Filter berdasarkan entry_shift_id"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Laporan tiket pending: masih PARKED atau pembayaran PENDING."""
    data = await crud_reports.get_pending_ticket_report(
        db=db,
        page=page,
        size=size,
        search=search,
        entry_date=entry_date,
        shift_id=shift_id,
    )
    return data


@router.get("/revenue", response_model=RevenueReportResponse)
async def revenue_report(
    start_date: date | None = Query(None, description="Format YYYY-MM-DD (WIB)"),
    end_date: date | None = Query(None, description="Format YYYY-MM-DD (WIB)"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Laporan pendapatan harian + rincian metode pembayaran.

    Tanpa parameter tanggal mencakup seluruh riwayat.
    """
    return await crud_reports.get_revenue_report(
        db=db, start_date=start_date, end_date=end_date
    )


@router.get("/vehicles", response_model=VehicleReportResponse)
async def vehicle_summary_report(
    start_date: date | None = Query(None, description="Format YYYY-MM-DD (WIB)"),
    end_date: date | None = Query(None, description="Format YYYY-MM-DD (WIB)"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Ringkasan kendaraan per jenis: jumlah transaksi dan pendapatan."""
    return await crud_reports.get_vehicle_summary_report(
        db=db, start_date=start_date, end_date=end_date
    )


@router.get("/operator-performance", response_model=OperatorPerformanceResponse)
async def operator_performance_report(
    start_date: date | None = Query(None, description="Format YYYY-MM-DD (WIB)"),
    end_date: date | None = Query(None, description="Format YYYY-MM-DD (WIB)"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Kinerja operator: sesi, transaksi yang ditangani, dan pendapatan."""
    return await crud_reports.get_operator_performance_report(
        db=db, start_date=start_date, end_date=end_date
    )


@router.get("/members", response_model=MemberReportResponse)
async def member_report(
    page: int = Query(1, ge=1, description="Nomor halaman"),
    size: int = Query(20, ge=1, le=100, description="Jumlah data per halaman (max 100)"),
    search: str | None = Query(
        None, description="Cari berdasarkan kode, nama, atau nomor polisi"
    ),
    status: MemberStatus | None = Query(None, description="Filter status member"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Laporan member (read-only) untuk role finance."""
    return await crud_reports.get_member_report(
        db=db, page=page, size=size, search=search, status=status
    )


@router.get("/gate-events", response_model=GateEventReportResponse)
async def gate_events_report(
    page: int = Query(1, ge=1, description="Nomor halaman"),
    size: int = Query(20, ge=1, le=100, description="Jumlah data per halaman (max 100)"),
    gate: str | None = Query(None, description="Filter kode gate (wire id, mis. '1')"),
    source: str | None = Query(None, description="Filter sumber event"),
    start_date: date | None = Query(None, description="Format YYYY-MM-DD (WIB)"),
    end_date: date | None = Query(None, description="Format YYYY-MM-DD (WIB)"),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Log akses gate dengan pagination dan filter."""
    return await crud_reports.get_gate_events_report(
        db=db,
        page=page,
        size=size,
        gate_code=gate,
        source=source,
        start_date=start_date,
        end_date=end_date,
    )


# ---------------------------------------------------------------------------
# Export (CSV / Excel / PDF) — same filters as above, full dataset download.
# ---------------------------------------------------------------------------


@router.get("/transactions/export")
async def export_transaction_report(
    format: ExportFormat = Query(ExportFormat.CSV, description="Format file: csv | xlsx | pdf"),
    search: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    status: ParkingStatus | None = Query(None),
    shift_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    data = await crud_reports.get_transaction_report(
        db=db,
        page=1,
        size=EXPORT_MAX_ROWS,
        search=search,
        start_date=start_date,
        end_date=end_date,
        status=status,
        shift_id=shift_id,
    )
    _guard_export_size(data["pagination"]["total_items"])

    rows = [
        [
            item["ticket_number"] or "-",
            item["police_number"] or "-",
            item["vehicle_type_name"] or "-",
            item["exit_operator_name"] or "-",
            fmt_dt(item["entry_time"]),
            fmt_dt(item["exit_time"]),
            duration_minutes(item["entry_time"], item["exit_time"]) if item["exit_time"] else None,
            item["payment_method"] or "-",
            rp(item["total_fee"]),
            enum_value(item["status_parking"]),
        ]
        for item in data["items"]
    ]
    doc = ExportDocument(
        filename_base="laporan-transaksi",
        title="Laporan Transaksi",
        period=period_label(start_date, end_date),
        summary_lines=_summary_lines(data["pagination"]["total_items"]),
        tables=[
            ExportTable(
                title="Transaksi",
                columns=[
                    "Kode Tiket",
                    "Plat Nomor",
                    "Jenis Kendaraan",
                    "Operator Keluar",
                    "Waktu Masuk",
                    "Waktu Keluar",
                    "Durasi (menit)",
                    "Metode Pembayaran",
                    "Total Biaya",
                    "Status Parkir",
                ],
                rows=rows,
            )
        ],
    )
    return build_export_response(doc, format)


@router.get("/pending-tickets/export")
async def export_pending_ticket_report(
    format: ExportFormat = Query(ExportFormat.CSV, description="Format file: csv | xlsx | pdf"),
    search: str | None = Query(None),
    entry_date: date | None = Query(None),
    shift_id: uuid.UUID | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    data = await crud_reports.get_pending_ticket_report(
        db=db,
        page=1,
        size=EXPORT_MAX_ROWS,
        search=search,
        entry_date=entry_date,
        shift_id=shift_id,
    )
    _guard_export_size(data["pagination"]["total_items"])

    rows = [
        [
            item["ticket_number"] or "-",
            item["police_number"] or "-",
            item["vehicle_type_name"] or "-",
            fmt_dt(item["entry_time"]),
            item["entry_gate_name"] or "-",
            enum_value(item["status_parking"]),
            item["payment_status"] or "BELUM BAYAR",
        ]
        for item in data["items"]
    ]
    doc = ExportDocument(
        filename_base="tiket-gantung",
        title="Laporan Tiket Gantung (Pending)",
        period=period_label(entry_date, entry_date),
        summary_lines=_summary_lines(data["pagination"]["total_items"]),
        tables=[
            ExportTable(
                title="Tiket Pending",
                columns=[
                    "Kode Tiket",
                    "Plat Nomor",
                    "Jenis Kendaraan",
                    "Waktu Masuk",
                    "Gate Masuk",
                    "Status Parkir",
                    "Status Pembayaran",
                ],
                rows=rows,
            )
        ],
    )
    return build_export_response(doc, format)


@router.get("/revenue/export")
async def export_revenue_report(
    format: ExportFormat = Query(ExportFormat.CSV, description="Format file: csv | xlsx | pdf"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    data = await crud_reports.get_revenue_report(
        db=db, start_date=start_date, end_date=end_date
    )
    summary = data["summary"]
    daily_rows = [
        [fmt_date(item["date"]), rp(item["total_revenue"]), item["total_transactions"]]
        for item in data["items"]
    ]
    method_rows = [
        [
            item["method"],
            item["total_transactions"],
            rp(item["total_amount"]),
            f"{item['percentage']}%",
        ]
        for item in data["payment_methods"]
    ]
    doc = ExportDocument(
        filename_base="laporan-pendapatan",
        title="Laporan Pendapatan",
        period=period_label(start_date, end_date),
        summary_lines=[
            f"Total Pendapatan: {rp(summary['total_revenue'])}",
            f"Jumlah Transaksi: {summary['total_transactions']}",
        ],
        tables=[
            ExportTable(
                title="Pendapatan Harian",
                columns=["Tanggal", "Pendapatan", "Jumlah Transaksi"],
                rows=daily_rows,
            ),
            ExportTable(
                title="Metode Pembayaran",
                columns=["Metode", "Jumlah Transaksi", "Total", "Persentase"],
                rows=method_rows,
            ),
        ],
    )
    return build_export_response(doc, format)


@router.get("/vehicles/export")
async def export_vehicle_summary_report(
    format: ExportFormat = Query(ExportFormat.CSV, description="Format file: csv | xlsx | pdf"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    data = await crud_reports.get_vehicle_summary_report(
        db=db, start_date=start_date, end_date=end_date
    )
    summary = data["summary"]
    rows = [
        [
            item["vehicle_type_name"],
            item["total_vehicles"],
            rp(item["total_revenue"]),
        ]
        for item in data["items"]
    ]
    doc = ExportDocument(
        filename_base="ringkasan-kendaraan",
        title="Ringkasan Kendaraan",
        period=period_label(start_date, end_date),
        summary_lines=[
            f"Total Pendapatan: {rp(summary['total_revenue'])}",
            f"Jumlah Transaksi: {summary['total_transactions']}",
        ],
        tables=[
            ExportTable(
                title="Per Jenis Kendaraan",
                columns=["Jenis Kendaraan", "Jumlah Transaksi", "Pendapatan"],
                rows=rows,
            )
        ],
    )
    return build_export_response(doc, format)


@router.get("/operator-performance/export")
async def export_operator_performance_report(
    format: ExportFormat = Query(ExportFormat.CSV, description="Format file: csv | xlsx | pdf"),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    data = await crud_reports.get_operator_performance_report(
        db=db, start_date=start_date, end_date=end_date
    )
    rows = [
        [
            item["operator_name"],
            item["total_sessions"],
            item["total_transactions"],
            rp(item["total_revenue"]),
            rp(item["avg_transaction_value"]),
        ]
        for item in data["items"]
    ]
    doc = ExportDocument(
        filename_base="kinerja-operator",
        title="Kinerja Operator",
        period=period_label(start_date, end_date),
        tables=[
            ExportTable(
                title="Kinerja Operator",
                columns=[
                    "Nama Operator",
                    "Jumlah Sesi",
                    "Jumlah Transaksi",
                    "Total Pendapatan",
                    "Rata-rata / Transaksi",
                ],
                rows=rows,
            )
        ],
    )
    return build_export_response(doc, format)


@router.get("/members/export")
async def export_member_report(
    format: ExportFormat = Query(ExportFormat.CSV, description="Format file: csv | xlsx | pdf"),
    search: str | None = Query(None),
    status: MemberStatus | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    data = await crud_reports.get_member_report(
        db=db, page=1, size=EXPORT_MAX_ROWS, search=search, status=status
    )
    _guard_export_size(data["pagination"]["total_items"])

    rows = [
        [
            item["member_code"],
            item["name"],
            ", ".join(v["police_number"] for v in item["vehicles"]) or "-",
            item["plan"]["name"] if item["plan"] else "-",
            item["plan"]["status"] if item["plan"] else "-",
            enum_value(item["status"]),
            fmt_dt(item["created_at"]),
        ]
        for item in data["items"]
    ]
    doc = ExportDocument(
        filename_base="laporan-member",
        title="Laporan Member",
        summary_lines=_summary_lines(data["pagination"]["total_items"]),
        tables=[
            ExportTable(
                title="Member",
                columns=[
                    "Kode Member",
                    "Nama",
                    "Plat Nomor",
                    "Paket",
                    "Status Paket",
                    "Status Member",
                    "Terdaftar",
                ],
                rows=rows,
            )
        ],
    )
    return build_export_response(doc, format)


@router.get("/gate-events/export")
async def export_gate_events_report(
    format: ExportFormat = Query(ExportFormat.CSV, description="Format file: csv | xlsx | pdf"),
    gate: str | None = Query(None),
    source: str | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    data = await crud_reports.get_gate_events_report(
        db=db,
        page=1,
        size=EXPORT_MAX_ROWS,
        gate_code=gate,
        source=source,
        start_date=start_date,
        end_date=end_date,
    )
    _guard_export_size(data["pagination"]["total_items"])

    rows = [
        [
            fmt_dt(item["ts"]),
            item["gate_code"] or "-",
            item["source"],
            item["method"] or "-",
            item["ticket_number"] or "-",
            item["detail"] or "-",
        ]
        for item in data["items"]
    ]
    doc = ExportDocument(
        filename_base="laporan-akses-gate",
        title="Laporan Akses Gate",
        period=period_label(start_date, end_date),
        summary_lines=_summary_lines(data["pagination"]["total_items"]),
        tables=[
            ExportTable(
                title="Akses Gate",
                columns=[
                    "Waktu",
                    "Gate",
                    "Sumber",
                    "Metode",
                    "Kode Tiket",
                    "Detail",
                ],
                rows=rows,
            )
        ],
    )
    return build_export_response(doc, format)