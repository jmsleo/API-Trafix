from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

SubscriptionStatus = Literal["active", "expired", "cancelled"]


class MemberSubscriptionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_id: UUID
    plan_id: UUID
    start_date: datetime
    end_date: datetime
    status: SubscriptionStatus = "active"

    @model_validator(mode="after")
    def _validate_date_range(self):
        if self.end_date <= self.start_date:
            raise ValueError("end_date must be after start_date")
        return self


class MemberSubscriptionCreate(MemberSubscriptionBase):
    pass


class MemberSubscriptionUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_id: UUID | None = None
    plan_id: UUID | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    status: SubscriptionStatus | None = None

    @model_validator(mode="after")
    def _validate_date_range(self):
        if (
            self.start_date is not None
            and self.end_date is not None
            and self.end_date <= self.start_date
        ):
            raise ValueError("end_date must be after start_date")
        return self


class MemberSubscriptionRead(MemberSubscriptionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
