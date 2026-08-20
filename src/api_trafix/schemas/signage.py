from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from api_trafix.models import SignageContentType, SignageStatus
from api_trafix.schemas.common import Name
from api_trafix.schemas.shift import ShiftTime

Code = Annotated[str, StringConstraints(min_length=1, max_length=50, strip_whitespace=True)]
Title = Annotated[str, StringConstraints(min_length=1, max_length=100, strip_whitespace=True)]
Body = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True)]
Location = Annotated[str, StringConstraints(max_length=200, strip_whitespace=True)]


class SignageBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    status: SignageStatus


class SignageContentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    content_type: SignageContentType
    is_active: bool


# ---------------------------------------------------------------------------
# Signage
# ---------------------------------------------------------------------------
class SignageBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name
    code: Code
    location: Location | None = None
    status: SignageStatus = SignageStatus.ACTIVE


class SignageCreate(SignageBase):
    pass


class SignageUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name | None = None
    code: Code | None = None
    location: Location | None = None
    status: SignageStatus | None = None


class SignageStatusUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    status: SignageStatus


class SignageRead(SignageBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class SignagePage(BaseModel):
    items: list[SignageRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ---------------------------------------------------------------------------
# Signage Content
# ---------------------------------------------------------------------------
class SignageContentBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    title: Title
    content_type: SignageContentType = SignageContentType.TEXT
    is_active: bool = True


class SignageContentCreate(SignageContentBase):
    body: Body


class SignageContentUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    title: Title | None = None
    content_type: SignageContentType | None = None
    body: str | None = None
    is_active: bool | None = None
    broadcast_start: datetime | None = None
    broadcast_end: datetime | None = None


class SignageContentStatusUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    is_active: bool


class SignageContentRead(SignageContentBase):
    id: UUID
    body: str | None = ""
    file_path: str | None = None
    mime_type: str | None = None
    file_size_bytes: int | None = None
    broadcast_start: datetime | None = None
    broadcast_end: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SignageContentPage(BaseModel):
    items: list[SignageContentRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ---------------------------------------------------------------------------
# Content Assignment
# ---------------------------------------------------------------------------
class SignageAssignmentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    signage_id: UUID
    content_id: UUID
    is_active: bool = True


class SignageAssignmentStatusUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    is_active: bool


class SignageAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    signage_id: UUID
    content_id: UUID
    is_active: bool
    signage: SignageBrief
    content: SignageContentBrief
    created_at: datetime
    updated_at: datetime


class SignageAssignmentPage(BaseModel):
    items: list[SignageAssignmentRead]
    total: int
    page: int
    page_size: int
    total_pages: int


# ---------------------------------------------------------------------------
# Content Scheduling
# ---------------------------------------------------------------------------
class SignageScheduleCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    signage_id: UUID
    content_id: UUID
    start_time: ShiftTime
    end_time: ShiftTime
    is_active: bool = True

    @model_validator(mode="after")
    def _validate_window(self):
        if self.end_time <= self.start_time:
            raise ValueError("end_time must be after start_time")
        return self


class SignageScheduleUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    signage_id: UUID | None = None
    content_id: UUID | None = None
    start_time: ShiftTime | None = None
    end_time: ShiftTime | None = None
    is_active: bool | None = None

    @model_validator(mode="after")
    def _validate_window(self):
        if (
            self.start_time is not None
            and self.end_time is not None
            and self.end_time <= self.start_time
        ):
            raise ValueError("end_time must be after start_time")
        return self


class SignageScheduleStatusUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    is_active: bool


class SignageScheduleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    signage_id: UUID
    content_id: UUID
    start_time: ShiftTime
    end_time: ShiftTime
    is_active: bool
    signage: SignageBrief
    content: SignageContentBrief
    created_at: datetime
    updated_at: datetime


class SignageSchedulePage(BaseModel):
    items: list[SignageScheduleRead]
    total: int
    page: int
    page_size: int
    total_pages: int
