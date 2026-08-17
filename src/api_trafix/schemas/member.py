from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, BeforeValidator, ConfigDict, StringConstraints, model_validator

from api_trafix.models.members import MemberStatus
from api_trafix.schemas.common import Email, Name, PhoneNumber

MemberCode = Annotated[str, StringConstraints(min_length=3, max_length=50, strip_whitespace=True)]


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


class PlanBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    duration_in_days: int
    price: int
    is_active: bool


class MemberBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    member_code: MemberCode
    name: Name
    email: Email | None = None
    phone_number: PhoneNumber | None = None
    status: MemberStatus
    created_by: UUID | None = None


class MemberCreate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name
    email: Email | None = None
    phone_number: PhoneNumber | None = None
    status: MemberStatus
    created_by: UUID | None = None
    police_number: VehiclePlate | None = None
    vehicle_type_id: UUID | None = None
    plan_id: UUID | None = None

    @model_validator(mode="after")
    def _vehicle_fields_together(self):
        if (self.police_number is None) != (self.vehicle_type_id is None):
            raise ValueError("police_number and vehicle_type_id must be provided together")
        return self


class MemberUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    name: Name | None = None
    email: Email | None = None
    phone_number: PhoneNumber | None = None
    status: MemberStatus | None = None
    created_by: UUID | None = None


class MemberVehicleTypeBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    code: str
    name: str


class MemberVehicleBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    police_number: str
    vehicle_type: MemberVehicleTypeBrief
    created_at: datetime


class MemberSubscriptionBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    plan: PlanBrief
    start_date: datetime
    end_date: datetime
    status: str


class MemberRead(MemberBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    vehicles: list[MemberVehicleBrief] = []
    subscriptions: list[MemberSubscriptionBrief] = []


class MemberPage(BaseModel):
    items: list[MemberRead]
    total: int
    page: int
    page_size: int
    total_pages: int
