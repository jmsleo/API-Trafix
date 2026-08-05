from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.users import UserRole, UserStatus


class UserBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    username: str
    role: UserRole
    status: UserStatus
    last_login: datetime | None = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    username: str | None = None
    password: str | None = None
    role: UserRole | None = None
    status: UserStatus | None = None
    last_login: datetime | None = None


class UserRead(UserBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
