from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ParkingRateTierBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parking_rate_id: UUID
    tier_order: int
    duration_from_minute: int
    duration_to_minute: int | None = None
    price: int


class ParkingRateTierCreate(ParkingRateTierBase):
    pass


class ParkingRateTierUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parking_rate_id: UUID | None = None
    tier_order: int | None = None
    duration_from_minute: int | None = None
    duration_to_minute: int | None = None
    price: int | None = None


class ParkingRateTierRead(ParkingRateTierBase):
    id: UUID
    created_at: datetime
