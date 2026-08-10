from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from api_trafix.models.members import MemberStatus
from api_trafix.schemas.common import Email, Name, PhoneNumber

MemberCode = Annotated[str, StringConstraints(min_length=3, max_length=50, strip_whitespace=True)]


class MemberBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    member_code: MemberCode
    name: Name
    email: Email | None = None
    phone_number: PhoneNumber | None = None
    status: MemberStatus
    created_by: UUID | None = None


class MemberCreate(MemberBase):
    pass


class MemberUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    member_code: MemberCode | None = None
    name: Name | None = None
    email: Email | None = None
    phone_number: PhoneNumber | None = None
    status: MemberStatus | None = None
    created_by: UUID | None = None


class MemberRead(MemberBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class MemberPage(BaseModel):
    items: list[MemberRead]
    total: int
    page: int
    page_size: int
    total_pages: int
