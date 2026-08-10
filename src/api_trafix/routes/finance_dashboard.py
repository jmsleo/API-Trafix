from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.crud import finance_dashboard as crud_finance
from api_trafix.config.database import get_db  # sesuaikan dengan lokasi dependency Anda
from api_trafix.schemas.finance_dashboard import (
    RevenueByShiftResponse,
    RevenueTodayResponse,
    VehicleDistributionResponse,
    ExecutiveInsightResponse,
    PaymentDistributionResponse
)

router = APIRouter(prefix="/finance/dashboard", tags=["Finance Dashboard"])


@router.get("/revenue/today", response_model=RevenueTodayResponse)
async def revenue_today(db: AsyncSession = Depends(get_db)):
    """Total pendapatan hari ini (WIB), dari transaksi COMPLETED."""
    data = await crud_finance.get_revenue_today(db)
    return data


@router.get("/revenue/shift", response_model=RevenueByShiftResponse)
async def revenue_by_shift(db: AsyncSession = Depends(get_db)):
    """Total pendapatan hari ini, dikelompokkan per exit_shift_id."""
    data = await crud_finance.get_revenue_by_shift(db)
    return data


@router.get("/vehicle-distribution", response_model=VehicleDistributionResponse)
async def vehicle_distribution(db: AsyncSession = Depends(get_db)):
    """Distribusi jumlah & persentase kendaraan berdasarkan vehicle_type_id, hari ini."""
    data = await crud_finance.get_vehicle_distribution(db)
    return data


@router.get("/payment-distribution", response_model=PaymentDistributionResponse)
async def payment_distribution(db: AsyncSession = Depends(get_db)):
    """Distribusi metode pembayaran hari ini (COMPLETED + SUCCESS)."""
    data = await crud_finance.get_payment_distribution(db)
    return data
 
 
@router.get("/executive-insight", response_model=ExecutiveInsightResponse)
async def executive_insight(db: AsyncSession = Depends(get_db)):
    """Insight operasional hari ini vs kemarin."""
    data = await crud_finance.get_executive_insight(db)
    return data