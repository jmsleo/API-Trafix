from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.schemas.common import NonNegativeInt, PositiveInt, ShortName


class VehicleTypeBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str


class SubscriptionPlanBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: ShortName
    duration_in_days: PositiveInt
    price: NonNegativeInt
    vehicle_type_id: UUID
    is_active: bool = True


class SubscriptionPlanCreate(SubscriptionPlanBase):
    pass


class SubscriptionPlanUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: ShortName | None = None
    duration_in_days: PositiveInt | None = None
    price: NonNegativeInt | None = None
    vehicle_type_id: UUID | None = None
    is_active: bool | None = None


class SubscriptionPlanRead(SubscriptionPlanBase):
    id: UUID
    vehicle_type: VehicleTypeBrief
    created_at: datetime
    updated_at: datetime


class SubscriptionPlanStatusUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    is_active: bool


class SubscriptionPlanPage(BaseModel):
    items: list[SubscriptionPlanRead]
    total: int
    page: int
    page_size: int
    total_pages: int
