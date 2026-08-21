import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
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

router = APIRouter(prefix="/finance/reports", tags=["Finance Reports"])


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