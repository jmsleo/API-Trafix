import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RevenueTodayResponse(BaseModel):
    """Total pendapatan hari ini (WIB)."""

    model_config = ConfigDict(from_attributes=True)

    date: str  
    total_revenue: int
    total_transactions: int


class RevenueByShiftItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    exit_shift_id: uuid.UUID | None
    total_revenue: int
    total_transactions: int


class RevenueByShiftResponse(BaseModel):
    date: str
    shifts: list[RevenueByShiftItem]


class VehicleDistributionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_type_id: uuid.UUID
    total_vehicles: int
    percentage: float  


class VehicleDistributionResponse(BaseModel):
    date: str
    total_vehicles: int
    distribution: list[VehicleDistributionItem]

class PaymentDistributionItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
 
    payment_method: str 
    total_transactions: int
    total_amount: int
    percentage: float  
 
 
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
    