from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.schemas.common import ModuleName, RoleName


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
