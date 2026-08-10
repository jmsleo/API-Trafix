from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.schemas.common import NonNegativeInt, PositiveInt, ShortName


class SubscriptionPlanBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: ShortName
    duration_in_days: PositiveInt
    price: NonNegativeInt
    is_active: bool = True


class SubscriptionPlanCreate(SubscriptionPlanBase):
    pass


class SubscriptionPlanUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: ShortName | None = None
    duration_in_days: PositiveInt | None = None
    price: NonNegativeInt | None = None
    is_active: bool | None = None


class SubscriptionPlanRead(SubscriptionPlanBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
