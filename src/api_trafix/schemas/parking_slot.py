from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from api_trafix.schemas.common import NonNegativeInt, PositiveInt


class ParkingSlotBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_type_id: UUID
    total_capacity: PositiveInt
    available_capacity: NonNegativeInt

    @model_validator(mode="after")
    def _validate_capacity(self):
        if self.available_capacity > self.total_capacity:
            raise ValueError("available_capacity must not exceed total_capacity")
        return self


class ParkingSlotCreate(ParkingSlotBase):
    pass


class ParkingSlotUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    vehicle_type_id: UUID | None = None
    total_capacity: PositiveInt | None = None
    available_capacity: NonNegativeInt | None = None

    @model_validator(mode="after")
    def _validate_capacity(self):
        if (
            self.total_capacity is not None
            and self.available_capacity is not None
            and self.available_capacity > self.total_capacity
        ):
            raise ValueError("available_capacity must not exceed total_capacity")
        return self


class ParkingSlotRead(ParkingSlotBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
