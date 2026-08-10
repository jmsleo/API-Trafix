from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.gates import GateStatus, GateType
from api_trafix.schemas.common import Name


class GateBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name
    type: GateType
    status: GateStatus


class GateCreate(GateBase):
    pass


class GateUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name | None = None
    type: GateType | None = None
    status: GateStatus | None = None


class GateRead(GateBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
