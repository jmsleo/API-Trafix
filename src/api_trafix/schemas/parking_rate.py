from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class ParkingRateBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    vehicle_type_id: UUID
    rate_type: str
    base_price: int
    max_daily_price: int | None = None
    status: str = "active"
    effective_from: datetime
    effective_until: datetime | None = None


class ParkingRateCreate(ParkingRateBase):
    pass


class ParkingRateUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    vehicle_type_id: UUID | None = None
    rate_type: str | None = None
    base_price: int | None = None
    max_daily_price: int | None = None
    status: str | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None


class ParkingRateRead(ParkingRateBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
