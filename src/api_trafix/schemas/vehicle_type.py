from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.vehicle_types import VehicleStatus


class VehicleTypeBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    name: str
    status: VehicleStatus


class VehicleTypeCreate(VehicleTypeBase):
    pass


class VehicleTypeUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str | None = None
    name: str | None = None
    status: VehicleStatus | None = None


class VehicleTypeRead(VehicleTypeBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
