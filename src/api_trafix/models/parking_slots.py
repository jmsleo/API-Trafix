import uuid
from datetime import datetime

from sqlalchemy import Integer, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api_trafix.config.database import Base
from api_trafix.models.vehicle_types import VehicleType


class ParkingSlot(Base):
    __tablename__ = "parking_slots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    vehicle_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicle_types.id"), nullable=False
    )

    total_capacity: Mapped[int] = mapped_column(Integer, nullable=False)
    available_capacity: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    vehicle_type: Mapped["VehicleType"] = relationship(back_populates="parking_slots")

    def __repr__(self) -> str:
        return (
            f"<ParkingSlot id={self.id} vehicle_type_id={self.vehicle_type_id} "
            f"available={self.available_capacity}/{self.total_capacity}>"
        )