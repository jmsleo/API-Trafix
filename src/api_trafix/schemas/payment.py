from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.payments import PaymentMethod, PaymentStatus


class PaymentBrief(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    amount: int
    method: PaymentMethod
    status: PaymentStatus
    reference_number: str | None
    paid_at: datetime | None


class PaymentRead(PaymentBrief):
    park_transaction_id: UUID
    created_at: datetime


class PaymentPage(BaseModel):
    items: list[PaymentRead]
    total: int
    page: int
    page_size: int
    total_pages: int
