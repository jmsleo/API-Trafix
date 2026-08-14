from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.schemas.common import Name, NonNegativeInt

RateStatus = Literal["active", "inactive"]
RateCategory = Literal["flat", "progresif"]


class ParkingRateBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name
    vehicle_type_id: UUID
    base_price: NonNegativeInt
    # Flat-mode tariff fields (gate cycle). fee_category mirrors the mock's
    # parking_fees.fee_category ("Flat"/"Progresif"), stored lowercase here.
    fee_category: RateCategory = "flat"
    grace_period_minutes: int | None = None
    ticket_charge: int | None = None
    stay_charge: int | None = None
    status: RateStatus = "active"


class ParkingRateCreate(ParkingRateBase):
    pass


class ParkingRateUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name | None = None
    vehicle_type_id: UUID | None = None
    base_price: NonNegativeInt | None = None
    fee_category: RateCategory | None = None
    grace_period_minutes: int | None = None
    ticket_charge: int | None = None
    stay_charge: int | None = None
    status: RateStatus | None = None


class ParkingRateRead(ParkingRateBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class ParkingRateStatusUpdate(BaseModel):
    status: RateStatus


class ParkingRatePage(BaseModel):
    items: list[ParkingRateRead]
    total: int
    page: int
    page_size: int
    total_pages: int
