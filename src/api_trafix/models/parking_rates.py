import uuid
from datetime import datetime
from typing import List, Optional

from sqlalchemy import String, Integer, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api_trafix.config.database import Base
from api_trafix.models.vehicle_types import VehicleType


class ParkingRate(Base):
    __tablename__ = "parking_rates"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    vehicle_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicle_types.id"), nullable=False
    )

    rate_type: Mapped[str] = mapped_column(String(20), nullable=False)  # enum(flat, progressive)

    base_price: Mapped[int] = mapped_column(Integer, nullable=False)
    max_daily_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="active"
    )  # enum(active, inactive)

    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    vehicle_type: Mapped["VehicleType"] = relationship(
    )
    tiers: Mapped[List["ParkingRateTier"]] = relationship(
        back_populates="parking_rate",
        cascade="all, delete-orphan",
        order_by="ParkingRateTier.tier_order",
    )

    def __repr__(self) -> str:
        return f"<ParkingRate id={self.id} name={self.name} type={self.rate_type}>"