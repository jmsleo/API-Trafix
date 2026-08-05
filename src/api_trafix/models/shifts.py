import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Enum, String, Time
from sqlalchemy.dialects.postgresql import UUID

from api_trafix.config.database import Base


class ShiftStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class Shift(Base):
    __tablename__ = "shifts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(50), nullable=False, unique=True)
    start_time = Column(Time(timezone=True), nullable=False)
    finish_time = Column(Time(timezone=True), nullable=False)
    crosses_midnight = Column(Boolean, nullable=False, default=False)
    status = Column(
        Enum(ShiftStatus, values_callable=lambda e: [v.value for v in e], name="shift_status"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
