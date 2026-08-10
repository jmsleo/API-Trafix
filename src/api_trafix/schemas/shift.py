from datetime import datetime, time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, model_validator

from api_trafix.models.shifts import ShiftStatus
from api_trafix.schemas.common import ShortName

CrossesMidnight = bool


class ShiftBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: ShortName
    start_time: time
    finish_time: time
    crosses_midnight: CrossesMidnight = False
    status: ShiftStatus

    @model_validator(mode="after")
    def _validate_crosses_midnight(self):
        if self.crosses_midnight:
            if self.finish_time >= self.start_time:
                raise ValueError("A shift crossing midnight must finish after midnight (finish < start)")
        else:
            if self.finish_time <= self.start_time:
                raise ValueError("A non-crossing shift must finish after it starts")
        return self


class ShiftCreate(ShiftBase):
    pass


class ShiftUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: ShortName | None = None
    start_time: time | None = None
    finish_time: time | None = None
    crosses_midnight: CrossesMidnight | None = None
    status: ShiftStatus | None = None

    @model_validator(mode="after")
    def _validate_crosses_midnight(self):
        start = self.start_time
        finish = self.finish_time
        crosses = self.crosses_midnight
        if start is not None and finish is not None and crosses is not None:
            if crosses and finish >= start:
                raise ValueError("A shift crossing midnight must finish after midnight (finish < start)")
            if not crosses and finish <= start:
                raise ValueError("A non-crossing shift must finish after it starts")
        return self


class ShiftRead(ShiftBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class ShiftPage(BaseModel):
    items: list[ShiftRead]
    total: int
    page: int
    page_size: int
    total_pages: int
