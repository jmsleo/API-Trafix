import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Enum, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api_trafix.config.database import Base


class RateStatus(str, enum.Enum):
    ACTIVE = "active"
    INACTIVE = "inactive"


class ParkingRate(Base):
    __tablename__ = "parking_rates"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), nullable=False)
    vehicle_type_id = Column(UUID(as_uuid=True), ForeignKey("vehicle_types.id"), nullable=False)
    base_price = Column(Integer, nullable=False)
    status = Column(
        Enum(RateStatus, values_callable=lambda e: [v.value for v in e], name="rate_status"),
        nullable=False,
        default=RateStatus.ACTIVE,
    )
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    vehicle_type = relationship("VehicleType")