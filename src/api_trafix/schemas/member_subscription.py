from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MemberSubscriptionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_id: UUID
    plan_id: UUID
    start_date: datetime
    end_date: datetime
    status: str = "active"


class MemberSubscriptionCreate(MemberSubscriptionBase):
    pass


class MemberSubscriptionUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_id: UUID | None = None
    plan_id: UUID | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    status: str | None = None


class MemberSubscriptionRead(MemberSubscriptionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
