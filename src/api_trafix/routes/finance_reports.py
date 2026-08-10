import uuid
from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.crud import finance_reports as crud_reports
from api_trafix.config.database import get_db  # sesuaikan dengan lokasi dependency Anda
from api_trafix.models import ParkingStatus
from api_trafix.schemas.finance_reports import (
    TransactionReportResponse,
    PendingTicketResponse
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