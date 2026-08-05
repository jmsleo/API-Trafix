from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.members import MemberStatus


class MemberBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_code: str
    name: str
    email: str | None = None
    phone_number: str | None = None
    status: MemberStatus
    created_by: UUID | None = None


class MemberCreate(MemberBase):
    pass


class MemberUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_code: str | None = None
    name: str | None = None
    email: str | None = None
    phone_number: str | None = None
    status: MemberStatus | None = None
    created_by: UUID | None = None


class MemberRead(MemberBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
