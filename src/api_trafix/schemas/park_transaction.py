from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from api_trafix.models.park_transactions import DetectionMethod, ParkingStatus
from api_trafix.schemas.common import NonNegativeInt, PoliceNumber, TicketNumber


class ParkTransactionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    ticket_number: TicketNumber | None = None
    police_number: PoliceNumber
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
    total_fee: NonNegativeInt = 0
    detection_method: DetectionMethod

    @model_validator(mode="after")
    def _validate_exit_fields(self):
        if self.exit_time is not None and self.exit_time < self.entry_time:
            raise ValueError("exit_time must not be before entry_time")
        exit_related = [self.exit_gate_id, self.exit_shift_id, self.exit_operator_id]
        if self.status_parking == ParkingStatus.COMPLETED:
            if self.exit_time is None or not all(exit_related):
                raise ValueError(
                    "Completed transactions require exit_time, exit_gate_id, exit_shift_id and exit_operator_id"
                )
        return self


class ParkTransactionCreate(ParkTransactionBase):
    pass


class ParkTransactionUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    ticket_number: TicketNumber | None = None
    police_number: PoliceNumber | None = None
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
    total_fee: NonNegativeInt | None = None
    detection_method: DetectionMethod | None = None

    @model_validator(mode="after")
    def _validate_exit_fields(self):
        if (
            self.entry_time is not None
            and self.exit_time is not None
            and self.exit_time < self.entry_time
        ):
            raise ValueError("exit_time must not be before entry_time")
        return self


class ParkTransactionRead(ParkTransactionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
