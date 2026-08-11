from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.park_transactions import DetectionMethod, ParkingStatus
from api_trafix.models.payments import PaymentMethod
from api_trafix.schemas.member_vehicle import MemberBrief, VehiclePlate, VehicleTypeBrief
from api_trafix.schemas.operator_session import GateBrief
from api_trafix.schemas.operator_shift_assignment import OperatorBrief, ShiftBrief
from api_trafix.schemas.payment import PaymentBrief


class MemberVehicleBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    police_number: str
    member: MemberBrief


class ParkTransactionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    police_number: VehiclePlate
    detection_method: DetectionMethod
    vehicle_type_id: UUID | None = None


class ParkTransactionCheckOut(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    payment_method: PaymentMethod


class ParkTransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticket_number: str | None
    police_number: str
    vehicle_type_id: UUID
    member_vehicle_id: UUID | None
    entry_time: datetime
    exit_time: datetime | None
    entry_gate_id: UUID
    exit_gate_id: UUID | None
    entry_shift_id: UUID
    exit_shift_id: UUID | None
    entry_operator_id: UUID
    exit_operator_id: UUID | None
    parking_rate_id: UUID | None
    status_parking: ParkingStatus
    is_member: bool
    total_fee: int
    detection_method: DetectionMethod
    vehicle_type: VehicleTypeBrief
    member_vehicle: MemberVehicleBrief | None
    entry_gate: GateBrief
    exit_gate: GateBrief | None
    entry_shift: ShiftBrief
    exit_shift: ShiftBrief | None
    entry_operator: OperatorBrief
    exit_operator: OperatorBrief | None
    payments: list[PaymentBrief]
    created_at: datetime
    updated_at: datetime


class ParkTransactionPage(BaseModel):
    items: list[ParkTransactionRead]
    total: int
    page: int
    page_size: int
    total_pages: int
