import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import Integer, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api_trafix.models.parking_rates import ParkingRate
from src.api_trafix.config.database import Base


class ParkingRateTier(Base):
    __tablename__ = "parking_rate_tiers"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    parking_rate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("parking_rates.id", ondelete="CASCADE"), nullable=False
    )

    tier_order: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_from_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_to_minute: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )  # null = seterusnya (tier terakhir/open-ended)
    price: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    # Relationships
    parking_rate: Mapped["ParkingRate"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<ParkingRateTier id={self.id} order={self.tier_order} "
            f"{self.duration_from_minute}-{self.duration_to_minute}min price={self.price}>"
        )
