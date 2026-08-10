import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RevenueTodayResponse(BaseModel):
    """Total pendapatan hari ini (WIB)."""

    model_config = ConfigDict(from_attributes=True)

    date: str  # tanggal WIB, format YYYY-MM-DD
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
    percentage: float  # dalam persen, dibulatkan 2 desimal


class VehicleDistributionResponse(BaseModel):
    date: str
    total_vehicles: int
    distribution: list[VehicleDistributionItem]