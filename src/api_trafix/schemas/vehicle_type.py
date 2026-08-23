from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.vehicle_types import VehicleStatus
from api_trafix.schemas.common import Code, Name, RupiahPrice


class VehicleTypeBase(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    code: Code
    name: Name
    price: RupiahPrice | None = None
    status: VehicleStatus


class VehicleTypeCreate(VehicleTypeBase):
    pass


class VehicleTypeUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True, str_strip_whitespace=True)

    code: Code | None = None
    name: Name | None = None
    price: RupiahPrice | None = None
    status: VehicleStatus | None = None


class VehicleTypeRead(VehicleTypeBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


class VehicleTypePage(BaseModel):
    items: list[VehicleTypeRead]
    total: int
    page: int
    page_size: int
    total_pages: int
