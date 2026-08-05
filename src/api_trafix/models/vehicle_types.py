import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, String
from sqlalchemy.dialects.postgresql import UUID

from api_trafix.config.database import Base


class VehicleStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class VehicleType(Base):
    __tablename__ = "vehicle_types"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    code = Column(String(20), nullable=False, unique=True)
    name = Column(String(100), nullable=False)
    status = Column(
        Enum(VehicleStatus, values_callable=lambda e: [v.value for v in e], name="vehicle_status"),
        nullable=False,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), onupdate=lambda: datetime.now(timezone.utc), nullable=False)
