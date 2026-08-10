from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints

from api_trafix.models.members import MemberStatus
from api_trafix.models.vehicle_types import VehicleStatus


def _normalize_plate(value: Any) -> Any:
    if value is None:
        return value
    return str(value).strip().upper()


VehiclePlate = Annotated[
    str,
    BeforeValidator(_normalize_plate),
    StringConstraints(
        min_length=3,
        max_length=20,
        strip_whitespace=True,
        pattern=r"^[A-Za-z0-9 .-]+$",
    ),
]


class MemberBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    member_code: str
    name: str
    status: MemberStatus


class VehicleTypeBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    code: str
    status: VehicleStatus


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
    member: MemberBrief
    vehicle_type: VehicleTypeBrief
    created_at: datetime
    updated_at: datetime


class MemberVehiclePage(BaseModel):
    items: list[MemberVehicleRead]
    total: int
    page: int
    page_size: int
    total_pages: int
