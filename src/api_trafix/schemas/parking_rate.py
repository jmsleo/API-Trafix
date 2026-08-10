from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from api_trafix.schemas.common import Name, NonNegativeInt

RateStatus = Literal["active", "inactive"]


class ParkingRateBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name
    vehicle_type_id: UUID
    base_price: NonNegativeInt
    max_daily_price: NonNegativeInt | None = None
    status: RateStatus = "active"
    effective_from: datetime
    effective_until: datetime | None = None

    @model_validator(mode="after")
    def _validate_effective_range(self):
        if self.effective_until is not None and self.effective_until < self.effective_from:
            raise ValueError("effective_until must not be before effective_from")
        return self


class ParkingRateCreate(ParkingRateBase):
    pass


class ParkingRateUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name | None = None
    vehicle_type_id: UUID | None = None
    base_price: NonNegativeInt | None = None
    max_daily_price: NonNegativeInt | None = None
    status: RateStatus | None = None
    effective_from: datetime | None = None
    effective_until: datetime | None = None

    @model_validator(mode="after")
    def _validate_effective_range(self):
        if (
            self.effective_from is not None
            and self.effective_until is not None
            and self.effective_until < self.effective_from
        ):
            raise ValueError("effective_until must not be before effective_from")
        return self


class ParkingRateRead(ParkingRateBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
