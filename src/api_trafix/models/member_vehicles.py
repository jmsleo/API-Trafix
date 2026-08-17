import uuid
from datetime import datetime

from sqlalchemy import String, ForeignKey, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api_trafix.models.members import Member
from api_trafix.models.vehicle_types import VehicleType
from api_trafix.config.database import Base


class MemberVehicle(Base):
    __tablename__ = "member_vehicles"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    member_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("members.id"), nullable=False
    )
    vehicle_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("vehicle_types.id"), nullable=False
    )

    police_number: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    member: Mapped["Member"] = relationship(back_populates="vehicles")
    vehicle_type: Mapped["VehicleType"] = relationship(back_populates="member_vehicles")

    def __repr__(self) -> str:
        return f"<MemberVehicle id={self.id} police_number={self.police_number}>"