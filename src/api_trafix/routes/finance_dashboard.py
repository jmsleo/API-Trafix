import uuid as uuid_mod
from datetime import date as date_type

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from api_trafix.config.database import get_db
from api_trafix.config.settings import get_settings
from api_trafix.core.dependencies import get_current_finance
from api_trafix.crud import finance_dashboard as crud_finance
from api_trafix.models import User
from api_trafix.schemas.finance_dashboard import (
    DashboardShiftItem,
    RevenueByShiftResponse,
    RevenueTodayResponse,
    VehicleDistributionResponse,
    ExecutiveInsightResponse,
    PaymentDistributionResponse,
)
from api_trafix.services import cache as cache_service

router = APIRouter(prefix="/finance/dashboard", tags=["Finance Dashboard"])


def _cache_key(
    name: str,
    date: date_type | None = None,
    shift_id: uuid_mod.UUID | None = None,
) -> str:
    date_label = str(date) if date else crud_finance.get_date_range_wib_to_utc()[2]
    shift_label = str(shift_id) if shift_id else "all"
    return f"finance:dashboard:{name}:{date_label}:{shift_label}"


@router.get("/shifts", response_model=list[DashboardShiftItem])
async def list_dashboard_shifts(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Daftar shift aktif (id + name), untuk dropdown filter."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        "finance:dashboard:shifts",
        lambda: crud_finance.get_active_shifts(db),
        ttl=ttl,
    )


@router.get("/revenue/today", response_model=RevenueTodayResponse)
async def revenue_today(
    date: date_type | None = Query(
        default=None, description="Tanggal WIB (YYYY-MM-DD), default hari ini"
    ),
    shift_id: uuid_mod.UUID | None = Query(
        default=None, description="Filter by shift ID"
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Total pendapatan hari ini (WIB), dari transaksi COMPLETED."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("revenue-today", date, shift_id),
        lambda: crud_finance.get_revenue_today(
            db, target_date=date, shift_id=shift_id
        ),
        ttl=ttl,
    )


@router.get("/revenue/shift", response_model=RevenueByShiftResponse)
async def revenue_by_shift(
    date: date_type | None = Query(
        default=None, description="Tanggal WIB (YYYY-MM-DD), default hari ini"
    ),
    shift_id: uuid_mod.UUID | None = Query(
        default=None, description="Filter by shift ID"
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Total pendapatan hari ini, dikelompokkan per exit_shift_id."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("revenue-by-shift", date, shift_id),
        lambda: crud_finance.get_revenue_by_shift(
            db, target_date=date, shift_id=shift_id
        ),
        ttl=ttl,
    )


@router.get("/vehicle-distribution", response_model=VehicleDistributionResponse)
async def vehicle_distribution(
    date: date_type | None = Query(
        default=None, description="Tanggal WIB (YYYY-MM-DD), default hari ini"
    ),
    shift_id: uuid_mod.UUID | None = Query(
        default=None, description="Filter by shift ID"
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Distribusi jumlah & persentase kendaraan berdasarkan vehicle_type_id."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("vehicle-distribution", date, shift_id),
        lambda: crud_finance.get_vehicle_distribution(
            db, target_date=date, shift_id=shift_id
        ),
        ttl=ttl,
    )


@router.get("/payment-distribution", response_model=PaymentDistributionResponse)
async def payment_distribution(
    date: date_type | None = Query(
        default=None, description="Tanggal WIB (YYYY-MM-DD), default hari ini"
    ),
    shift_id: uuid_mod.UUID | None = Query(
        default=None, description="Filter by shift ID"
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Distribusi metode pembayaran (COMPLETED + SUCCESS)."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("payment-distribution", date, shift_id),
        lambda: crud_finance.get_payment_distribution(
            db, target_date=date, shift_id=shift_id
        ),
        ttl=ttl,
    )


@router.get("/executive-insight", response_model=ExecutiveInsightResponse)
async def executive_insight(
    date: date_type | None = Query(
        default=None, description="Tanggal WIB (YYYY-MM-DD), default hari ini"
    ),
    shift_id: uuid_mod.UUID | None = Query(
        default=None, description="Filter by shift ID"
    ),
    db: AsyncSession = Depends(get_db),
    _: User = Depends(get_current_finance),
):
    """Insight operasional hari ini vs kemarin."""
    ttl = get_settings().redis_cache_expire
    return await cache_service.get_or_set(
        _cache_key("executive-insight", date, shift_id),
        lambda: crud_finance.get_executive_insight(
            db, target_date=date, shift_id=shift_id
        ),
        ttl=ttl,
    )