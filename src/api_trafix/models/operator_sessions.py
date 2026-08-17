import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Enum, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api_trafix.config.database import Base


class OperatorSessionStatus(enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class OperatorSession(Base):
    __tablename__ = "operator_sessions"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False
    )
    gate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gates.id"), nullable=False
    )
    login_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    logout_time: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[OperatorSessionStatus] = mapped_column(
        Enum(
            OperatorSessionStatus,
            values_callable=lambda e: [v.value for v in e],
            name="operator_session_status",
        ),
        nullable=False,
        default=OperatorSessionStatus.ACTIVE,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    user = relationship("User", foreign_keys=[user_id], back_populates="operator_sessions")
    shift = relationship("Shift", foreign_keys=[shift_id], back_populates="operator_sessions")
    gate = relationship("Gate", foreign_keys=[gate_id], back_populates="operator_sessions")