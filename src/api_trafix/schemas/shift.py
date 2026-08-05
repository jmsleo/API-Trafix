from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.shifts import ShiftStatus


class ShiftBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    start_time: time
    finish_time: time
    crosses_midnight: bool = False
    status: ShiftStatus


class ShiftCreate(ShiftBase):
    pass


class ShiftUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str | None = None
    start_time: time | None = None
    finish_time: time | None = None
    crosses_midnight: bool | None = None
    status: ShiftStatus | None = None


class ShiftRead(ShiftBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
