from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.schemas.common import ModuleName, RoleName


class UserBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    username: str


class AuditLogBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    user_id: UUID | None = None
    role: RoleName | None = None
    module: ModuleName
    action: ModuleName
    description: str | None = None


class AuditLogCreate(AuditLogBase):
    pass


class AuditLogUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    user_id: UUID | None = None
    role: RoleName | None = None
    module: ModuleName | None = None
    action: ModuleName | None = None
    description: str | None = None


class AuditLogRead(AuditLogBase):
    id: UUID
    created_at: datetime
    user: UserBrief | None = None


class AuditLogPage(BaseModel):
    items: list[AuditLogRead]
    total: int
    page: int
    page_size: int
    total_pages: int
