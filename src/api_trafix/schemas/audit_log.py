from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class AuditLogBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID | None = None
    role: str | None = None
    module: str
    action: str
    description: str | None = None


class AuditLogCreate(AuditLogBase):
    pass


class AuditLogUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID | None = None
    role: str | None = None
    module: str | None = None
    action: str | None = None
    description: str | None = None


class AuditLogRead(AuditLogBase):
    id: UUID
    created_at: datetime
