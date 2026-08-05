from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from api_trafix.schemas.common import NonNegativeInt


class ParkingRateTierBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parking_rate_id: UUID
    tier_order: NonNegativeInt
    duration_from_minute: NonNegativeInt
    duration_to_minute: NonNegativeInt | None = None
    price: NonNegativeInt

    @model_validator(mode="after")
    def _validate_duration_range(self):
        if self.duration_to_minute is not None and self.duration_to_minute <= self.duration_from_minute:
            raise ValueError("duration_to_minute must be greater than duration_from_minute")
        return self


class ParkingRateTierCreate(ParkingRateTierBase):
    pass


class ParkingRateTierUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parking_rate_id: UUID | None = None
    tier_order: NonNegativeInt | None = None
    duration_from_minute: NonNegativeInt | None = None
    duration_to_minute: NonNegativeInt | None = None
    price: NonNegativeInt | None = None

    @model_validator(mode="after")
    def _validate_duration_range(self):
        if (
            self.duration_from_minute is not None
            and self.duration_to_minute is not None
            and self.duration_to_minute <= self.duration_from_minute
        ):
            raise ValueError("duration_to_minute must be greater than duration_from_minute")
        return self


class ParkingRateTierRead(ParkingRateTierBase):
    id: UUID
    created_at: datetime
