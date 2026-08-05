from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ParkingSlotBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_type_id: UUID
    total_capacity: int
    available_capacity: int


class ParkingSlotCreate(ParkingSlotBase):
    pass


class ParkingSlotUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_type_id: UUID | None = None
    total_capacity: int | None = None
    available_capacity: int | None = None


class ParkingSlotRead(ParkingSlotBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
