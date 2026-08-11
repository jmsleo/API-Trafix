from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.config.settings import get_settings
from api_trafix.core.dependencies import get_current_finance
from api_trafix.crud import finance_dashboard as crud_finance
from api_trafix.models import User
from api_trafix.schemas.finance_dashboard import (
    RevenueByShiftResponse,
    RevenueTodayResponse,
    VehicleDistributionResponse,
    ExecutiveInsightResponse,
    PaymentDistributionResponse
)
from api_trafix.services import cache as cache_service

router = APIRouter(prefix="/finance/dashboard", tags=["Finance Dashboard"])


def _cache_key(name: str) -> str:
    _, _, date_label = crud_finance.get_today_range_wib_to_utc()
    return f"finance:dashboard:{name}:{date_label}"


@router.get("/revenue/today", response_model=RevenueTodayResponse)
async def revenue_today(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Total pendapatan hari ini (WIB), dari transaksi COMPLETED."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("revenue-today"),
        lambda: crud_finance.get_revenue_today(db),
        ttl=ttl,
    )


@router.get("/revenue/shift", response_model=RevenueByShiftResponse)
async def revenue_by_shift(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Total pendapatan hari ini, dikelompokkan per exit_shift_id."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("revenue-by-shift"),
        lambda: crud_finance.get_revenue_by_shift(db),
        ttl=ttl,
    )


@router.get("/vehicle-distribution", response_model=VehicleDistributionResponse)
async def vehicle_distribution(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Distribusi jumlah & persentase kendaraan berdasarkan vehicle_type_id, hari ini."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("vehicle-distribution"),
        lambda: crud_finance.get_vehicle_distribution(db),
        ttl=ttl,
    )


@router.get("/payment-distribution", response_model=PaymentDistributionResponse)
async def payment_distribution(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Distribusi metode pembayaran hari ini (COMPLETED + SUCCESS)."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("payment-distribution"),
        lambda: crud_finance.get_payment_distribution(db),
        ttl=ttl,
    )


@router.get("/executive-insight", response_model=ExecutiveInsightResponse)
async def executive_insight(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Insight operasional hari ini vs kemarin."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("executive-insight"),
        lambda: crud_finance.get_executive_insight(db),
        ttl=ttl,
    )