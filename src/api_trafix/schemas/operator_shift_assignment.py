from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.operator_shift_assignments import OperatorShiftAssignmentStatus
from api_trafix.schemas.shift import ShiftTime


class OperatorBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    username: str


class ShiftBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    start_time: ShiftTime
    finish_time: ShiftTime
    crosses_midnight: bool


class OperatorShiftAssignmentCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    operator_id: UUID
    shift_id: UUID


class OperatorShiftAssignmentUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    operator_id: UUID
    shift_id: UUID
    status: OperatorShiftAssignmentStatus


class OperatorShiftAssignmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    operator_id: UUID
    shift_id: UUID
    status: OperatorShiftAssignmentStatus
    operator: OperatorBrief
    shift: ShiftBrief
    created_at: datetime
    updated_at: datetime


class OperatorShiftAssignmentPage(BaseModel):
    items: list[OperatorShiftAssignmentRead]
    total: int
    page: int
    page_size: int
    total_pages: int
