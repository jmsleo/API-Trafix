from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.schemas.member_vehicle import MemberBrief

SubscriptionStatus = Literal["active", "expired", "cancelled"]


class PlanBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    duration_in_days: int
    price: int
    is_active: bool


class MemberSubscriptionCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    member_id: UUID
    plan_id: UUID
    start_date: datetime | None = None


class MemberSubscriptionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    member_id: UUID
    plan_id: UUID
    start_date: datetime
    end_date: datetime
    status: SubscriptionStatus
    member: MemberBrief
    plan: PlanBrief
    created_at: datetime
    updated_at: datetime


class MemberSubscriptionPage(BaseModel):
    items: list[MemberSubscriptionRead]
    total: int
    page: int
    page_size: int
    total_pages: int
