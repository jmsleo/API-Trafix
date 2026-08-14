from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from api_trafix.schemas.common import IpAddress, Name

DeviceType = Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
DeviceStatus = Literal["online", "offline"]


class DeviceBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    gate_id: UUID
    name: Name
    type: DeviceType
    ip_address: IpAddress
    config: dict[str, Any] | None = Field(default=None, max_length=1000)
    status: DeviceStatus = "offline"
    last_heartbeat: datetime | None = None


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    gate_id: UUID | None = None
    name: Name | None = None
    type: DeviceType | None = None
    ip_address: IpAddress | None = None
    config: dict[str, Any] | None = Field(default=None, max_length=1000)
    status: DeviceStatus | None = None
    last_heartbeat: datetime | None = None


class DeviceRead(DeviceBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class DevicePage(BaseModel):
    items: list[DeviceRead]
    total: int
    page: int
    page_size: int
    total_pages: int
