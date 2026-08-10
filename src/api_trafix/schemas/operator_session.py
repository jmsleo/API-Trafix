from datetime import datetime, time
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.gates import GateStatus, GateType
from api_trafix.models.operator_sessions import OperatorSessionStatus
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


class GateBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    type: GateType
    status: GateStatus


class OperatorSessionStart(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    shift_id: UUID
    gate_id: UUID


class OperatorSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    shift_id: UUID
    gate_id: UUID
    login_time: datetime
    logout_time: datetime | None = None
    status: OperatorSessionStatus
    user: OperatorBrief
    shift: ShiftBrief
    gate: GateBrief
    created_at: datetime
    updated_at: datetime


class OperatorSessionPage(BaseModel):
    items: list[OperatorSessionRead]
    total: int
    page: int
    page_size: int
    total_pages: int
