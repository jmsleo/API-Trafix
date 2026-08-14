from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints

from api_trafix.models.gates import GateStatus, GateType
from api_trafix.schemas.common import Name

# The wire id the LPR/gate hardware uses ("1", "2"), decoupled from the UUID
# primary key. The gate cycle maps a device's gate number to this value.
GateCode = Annotated[str, StringConstraints(min_length=1, max_length=16, strip_whitespace=True)]


class GateBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name
    gate_code: GateCode | None = None
    type: GateType
    status: GateStatus


class GateCreate(GateBase):
    pass


class GateUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name | None = None
    gate_code: GateCode | None = None
    type: GateType | None = None
    status: GateStatus | None = None


class GateRead(GateBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class GatePage(BaseModel):
    items: list[GateRead]
    total: int
    page: int
    page_size: int
    total_pages: int
