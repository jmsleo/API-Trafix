from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.gates import GateStatus, GateType
from api_trafix.models.operator_sessions import OperatorSessionStatus
from api_trafix.schemas.operator_shift_assignment import OperatorBrief, ShiftBrief


class GateBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    gate_code: str
    type: GateType
    status: GateStatus


class OperatorSessionStart(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    # Optional: when omitted the backend resolves the operator's CURRENT
    # assigned shift (the one whose window covers "now" in WIB) and rejects
    # login outside any shift window.
    shift_id: UUID | None = None
    # Optional: when omitted the backend resolves the single configured exit
    # gate automatically — operators serve gate-out only.
    gate_id: UUID | None = None


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
