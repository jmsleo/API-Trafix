import uuid
from datetime import date, datetime
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict

from api_trafix.models import ParkingStatus

T = TypeVar("T")


class PaginationMeta(BaseModel):
    total_items: int
    total_pages: int
    current_page: int
    size: int


class TransactionReportItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    ticket_number: str
    police_number: str
    vehicle_type_id: uuid.UUID
    entry_time: datetime
    exit_time: datetime | None
    entry_shift_id: uuid.UUID | None
    exit_shift_id: uuid.UUID | None
    status_parking: ParkingStatus
    total_fee: int


class TransactionReportResponse(BaseModel):
    items: list[TransactionReportItem]
    pagination: PaginationMeta