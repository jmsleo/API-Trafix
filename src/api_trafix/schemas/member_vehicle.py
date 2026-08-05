from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

from api_trafix.schemas.common import NonNegativeInt

VehiclePlate = Annotated[
    str,
    StringConstraints(
        min_length=3,
        max_length=20,
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9 .-]+$",
    ),
]


class MemberVehicleBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    member_id: UUID
    vehicle_type_id: UUID
    police_number: VehiclePlate


class MemberVehicleCreate(MemberVehicleBase):
    pass


class MemberVehicleUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    member_id: UUID | None = None
    vehicle_type_id: UUID | None = None
    police_number: VehiclePlate | None = None


class MemberVehicleRead(MemberVehicleBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
