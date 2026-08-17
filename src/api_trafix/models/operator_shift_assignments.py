import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api_trafix.config.database import Base


class OperatorShiftAssignmentStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class OperatorShiftAssignment(Base):
    __tablename__ = "operator_shift_assignments"
    __table_args__ = (
        UniqueConstraint("operator_id", "shift_id", name="uq_operator_shift_assignment"),
    )

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    operator_id = Column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    shift_id = Column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False
    )
    status = Column(
        Enum(
            OperatorShiftAssignmentStatus,
            values_callable=lambda e: [v.value for v in e],
            name="operator_shift_assignment_status",
        ),
        nullable=False,
        default=OperatorShiftAssignmentStatus.ACTIVE,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)

    operator = relationship("User", foreign_keys=[operator_id], back_populates="operator_shift_assignments")
    shift = relationship("Shift", foreign_keys=[shift_id], back_populates="operator_shift_assignments")
