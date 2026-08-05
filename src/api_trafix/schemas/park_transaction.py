from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.park_transactions import DetectionMethod, ParkingStatus


class ParkTransactionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_number: str | None = None
    police_number: str
    vehicle_type_id: UUID
    member_vehicle_id: UUID | None = None
    entry_time: datetime
    exit_time: datetime | None = None
    entry_gate_id: UUID
    exit_gate_id: UUID | None = None
    entry_shift_id: UUID
    exit_shift_id: UUID | None = None
    entry_operator_id: UUID
    exit_operator_id: UUID | None = None
    parking_rate_id: UUID | None = None
    status_parking: ParkingStatus = ParkingStatus.PARKED
    is_member: bool = False
    total_fee: int = 0
    detection_method: DetectionMethod


class ParkTransactionCreate(ParkTransactionBase):
    pass


class ParkTransactionUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    ticket_number: str | None = None
    police_number: str | None = None
    vehicle_type_id: UUID | None = None
    member_vehicle_id: UUID | None = None
    entry_time: datetime | None = None
    exit_time: datetime | None = None
    entry_gate_id: UUID | None = None
    exit_gate_id: UUID | None = None
    entry_shift_id: UUID | None = None
    exit_shift_id: UUID | None = None
    entry_operator_id: UUID | None = None
    exit_operator_id: UUID | None = None
    parking_rate_id: UUID | None = None
    status_parking: ParkingStatus | None = None
    is_member: bool | None = None
    total_fee: int | None = None
    detection_method: DetectionMethod | None = None


class ParkTransactionRead(ParkTransactionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
