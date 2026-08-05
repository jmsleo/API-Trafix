import uuid
from datetime import datetime
from typing import Optional, Any

from sqlalchemy import String, ForeignKey, DateTime, JSON, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from api_trafix.config.database import Base
from api_trafix.models.gates import Gate 


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    gate_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("gates.id"), nullable=False
    )

    name: Mapped[str] = mapped_column(String(100), nullable=False)
    type: Mapped[str] = mapped_column(String(50), nullable=False)  # Controller, MQTT, Camera LPR, dll
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)

    config: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="offline"
    )  # enum(online, offline, trouble)

    last_heartbeat: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )  # monitoring real-time

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    gate: Mapped["Gate"] = relationship()

    def __repr__(self) -> str:
        return f"<Device id={self.id} name={self.name} status={self.status}>"
