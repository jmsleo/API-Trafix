import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Enum, DateTime, ForeignKey, String, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api_trafix.config.database import Base


class PaymentMethod(enum.Enum):
    CASH = "Cash"
    QRIS = "QRIS"
    EMONEY = "Emoney"


class PaymentStatus(enum.Enum):
    PENDING = "Pending"
    SUCCESS = "Success"
    FAILED = "Failed"
    REFUNDED = "Refunded"


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    park_transaction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("park_transactions.id"), nullable=False
    )
    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    method: Mapped[PaymentMethod] = mapped_column(
        Enum(
            PaymentMethod,
            values_callable=lambda e: [v.value for v in e],
            name="payment_method",
        ),
        nullable=False,
    )
    status: Mapped[PaymentStatus] = mapped_column(
        Enum(
            PaymentStatus,
            values_callable=lambda e: [v.value for v in e],
            name="payment_status",
        ),
        nullable=False,
        default=PaymentStatus.PENDING,
    )
    reference_number: Mapped[str | None] = mapped_column(String, nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )

    # Relationship internal (tabel 14-16)
    park_transaction: Mapped["ParkTransaction"] = relationship()