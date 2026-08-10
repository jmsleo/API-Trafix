from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.schemas.common import Name, NonNegativeInt

RateStatus = Literal["active", "inactive"]


class ParkingRateBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name
    vehicle_type_id: UUID
    base_price: NonNegativeInt
    status: RateStatus = "active"


class ParkingRateCreate(ParkingRateBase):
    pass


class ParkingRateUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name | None = None
    vehicle_type_id: UUID | None = None
    base_price: NonNegativeInt | None = None
    status: RateStatus | None = None


class ParkingRateRead(ParkingRateBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
