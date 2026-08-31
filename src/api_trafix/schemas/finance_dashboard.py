import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DashboardShiftItem(BaseModel):
    """Shift item untuk dropdown filter dashboard."""
    id: uuid.UUID
    name: str


class RevenueTodayResponse(BaseModel):
    """Total pendapatan hari ini (WIB)."""

    model_config = ConfigDict(from_attributes=True)

    date: str  # tanggal WIB, format YYYY-MM-DD
    total_revenue: int
    total_transactions: int


class RevenueByShiftItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exit_shift_id: uuid.UUID | None
    shift_name: str | None = None
    total_revenue: int
    total_transactions: int


class RevenueByShiftResponse(BaseModel):
    date: str
    shifts: list[RevenueByShiftItem]


class VehicleDistributionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_type_id: uuid.UUID
    vehicle_type_name: str | None = None
    total_vehicles: int
    percentage: float  # dalam persen, dibulatkan 2 desimal


class VehicleDistributionResponse(BaseModel):
    date: str
    total_vehicles: int
    distribution: list[VehicleDistributionItem]

class PaymentDistributionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
 
    payment_method: str  # Cash / QRIS / Emoney
    total_transactions: int
    total_amount: int
    percentage: float  # persentase terhadap total_amount, dibulatkan 2 desimal
 
 
class PaymentDistributionResponse(BaseModel):
    date: str
    total_transactions: int
    total_amount: int
    distribution: list[PaymentDistributionItem]
 
 
class ExecutiveInsightResponse(BaseModel):
    date: str
    revenue_today: int
    revenue_yesterday: int
    revenue_growth_percentage: float
    highest_revenue_shift_id: uuid.UUID | None
    total_pending_tickets: int