import uuid
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from api_trafix.config.database import Base


class ParkingRateTier(Base):
    __tablename__ = "parking_rate_tiers"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    parking_rate_id = Column(
        UUID(as_uuid=True),
        ForeignKey("parking_rates.id", ondelete="CASCADE"),
        nullable=False,
    )
    tier_order = Column(Integer, nullable=False)
    duration_from_minute = Column(Integer, nullable=False)
    duration_to_minute = Column(Integer, nullable=True)  # null = seterusnya
    price = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False)

    parking_rate = relationship("ParkingRate", back_populates="tiers")