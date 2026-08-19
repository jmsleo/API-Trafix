import uuid
from datetime import datetime

from sqlalchemy import DateTime, JSON, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from api_trafix.config.database import Base


class SystemConfig(Base):
    """Runtime configuration overrides persisted to the database.

    Values here win over environment-based defaults. They are merged into the
    effective settings when the API starts, so a change to MQTT config made
    through the API takes effect on the next start (documented as
    "applies on restart" in the UI).
    """

    __tablename__ = "system_config"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # Section/namespace of the setting, e.g. "mqtt".
    section: Mapped[str] = mapped_column(String(50), nullable=False)
    # Setting key without the section prefix, e.g. "host".
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )