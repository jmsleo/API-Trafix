from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class MemberVehicleBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_id: UUID
    vehicle_type_id: UUID
    police_number: str


class MemberVehicleCreate(MemberVehicleBase):
    pass


class MemberVehicleUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    member_id: UUID | None = None
    vehicle_type_id: UUID | None = None
    police_number: str | None = None


class MemberVehicleRead(MemberVehicleBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
