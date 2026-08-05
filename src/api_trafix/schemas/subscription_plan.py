from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class SubscriptionPlanBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    duration_in_days: int
    price: int
    is_active: bool = True


class SubscriptionPlanCreate(SubscriptionPlanBase):
    pass


class SubscriptionPlanUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    duration_in_days: int | None = None
    price: int | None = None
    is_active: bool | None = None


class SubscriptionPlanRead(SubscriptionPlanBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
