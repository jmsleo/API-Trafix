import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from api_trafix.models import MemberStatus, ParkingStatus


class PaginationMeta(BaseModel):
    total_items: int
    total_pages: int
    current_page: int
    size: int


class TransactionReportItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_number: str | None = None
    police_number: str | None = None
    vehicle_type_id: uuid.UUID
    vehicle_type_name: str | None = None
    entry_time: datetime
    exit_time: datetime | None
    entry_shift_id: uuid.UUID | None
    exit_shift_id: uuid.UUID | None
    status_parking: ParkingStatus
    total_fee: int
    exit_operator_name: str | None = None
    payment_method: str | None = None


class TransactionReportResponse(BaseModel):
    items: list[TransactionReportItem]
    pagination: PaginationMeta

class PendingTicketItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
 
    id: uuid.UUID
    ticket_number: str | None = None
    police_number: str | None = None
    vehicle_type_id: uuid.UUID
    vehicle_type_name: str | None = None
    entry_time: datetime
    entry_shift_id: uuid.UUID | None
    status_parking: ParkingStatus
    payment_status: str | None  # None jika belum ada record Payment sama sekali
    entry_gate_name: str | None = None
 
 
class PendingTicketResponse(BaseModel):
    items: list[PendingTicketItem]
    pagination: PaginationMeta


# ---------------------------------------------------------------------------
# Revenue report (laporan pendapatan)
# ---------------------------------------------------------------------------
class RevenueSummary(BaseModel):
    total_revenue: int
    total_transactions: int


class RevenueDailyItem(BaseModel):
    date: date
    total_revenue: int
    total_transactions: int


class PaymentMethodBreakdownItem(BaseModel):
    method: str
    total_transactions: int
    total_amount: int
    percentage: float


class RevenueReportResponse(BaseModel):
    summary: RevenueSummary
    items: list[RevenueDailyItem]
    payment_methods: list[PaymentMethodBreakdownItem]


# ---------------------------------------------------------------------------
# Vehicle summary report (ringkasan kendaraan)
# ---------------------------------------------------------------------------
class VehicleReportItem(BaseModel):
    vehicle_type_id: uuid.UUID
    vehicle_type_name: str
    total_vehicles: int
    total_revenue: int


class VehicleReportResponse(BaseModel):
    summary: RevenueSummary
    items: list[VehicleReportItem]


# ---------------------------------------------------------------------------
# Operator performance report (kinerja operator)
# ---------------------------------------------------------------------------
class OperatorPerformanceItem(BaseModel):
    operator_id: uuid.UUID
    operator_name: str
    total_sessions: int
    total_transactions: int
    total_revenue: int
    avg_transaction_value: float


class OperatorPerformanceResponse(BaseModel):
    items: list[OperatorPerformanceItem]


# ---------------------------------------------------------------------------
# Member report (laporan member)
# ---------------------------------------------------------------------------
class MemberReportVehicleItem(BaseModel):
    police_number: str
    vehicle_type_name: str | None = None


class MemberReportPlanItem(BaseModel):
    name: str
    price: int
    status: str


class MemberReportItem(BaseModel):
    id: uuid.UUID
    member_code: str
    name: str
    status: MemberStatus
    created_at: datetime
    vehicles: list[MemberReportVehicleItem] = []
    plan: MemberReportPlanItem | None = None


class MemberReportResponse(BaseModel):
    items: list[MemberReportItem]
    pagination: PaginationMeta


# ---------------------------------------------------------------------------
# Gate access log report (laporan akses gate)
# ---------------------------------------------------------------------------
class GateEventReportItem(BaseModel):
    id: uuid.UUID
    ts: datetime
    gate_code: str | None
    source: str
    method: str | None
    ticket_number: str | None
    detail: str | None


class GateEventReportResponse(BaseModel):
    items: list[GateEventReportItem]
    pagination: PaginationMeta