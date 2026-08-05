from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class DeviceBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gate_id: UUID
    name: str
    type: str
    ip_address: str
    config: dict[str, Any] | None = None
    status: str = "offline"
    last_heartbeat: datetime | None = None


class DeviceCreate(DeviceBase):
    pass


class DeviceUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    gate_id: UUID | None = None
    name: str | None = None
    type: str | None = None
    ip_address: str | None = None
    config: dict[str, Any] | None = None
    status: str | None = None
    last_heartbeat: datetime | None = None


class DeviceRead(DeviceBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
