from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from api_trafix.models.payments import PaymentMethod, PaymentStatus


class PaymentBase(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    park_transaction_id: UUID
    amount: int
    method: PaymentMethod
    status: PaymentStatus = PaymentStatus.PENDING
    reference_number: str | None = None
    paid_at: datetime | None = None


class PaymentCreate(PaymentBase):
    pass


class PaymentUpdate(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    park_transaction_id: UUID | None = None
    amount: int | None = None
    method: PaymentMethod | None = None
    status: PaymentStatus | None = None
    reference_number: str | None = None
    paid_at: datetime | None = None


class PaymentRead(PaymentBase):
    id: UUID
    created_at: datetime
