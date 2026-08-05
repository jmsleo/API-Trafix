from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.operator_sessions import OperatorSessionStatus


class OperatorSessionBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID
    shift_id: UUID
    gate_id: UUID
    login_time: datetime
    logout_time: datetime | None = None
    status: OperatorSessionStatus = OperatorSessionStatus.ACTIVE


class OperatorSessionCreate(OperatorSessionBase):
    pass


class OperatorSessionUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: UUID | None = None
    shift_id: UUID | None = None
    gate_id: UUID | None = None
    login_time: datetime | None = None
    logout_time: datetime | None = None
    status: OperatorSessionStatus | None = None


class OperatorSessionRead(OperatorSessionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
